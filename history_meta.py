"""
Versioned mixin class and other utilities.
https://docs.sqlalchemy.org/en/20/_modules/examples/versioned_history/history_meta.html
https://github.com/sqlalchemy/sqlalchemy/discussions/10618
"""

import datetime
import uuid
import pytz
from itertools import tee
from typing import Iterable
from dateutil.parser import parse, ParserError

from sqlalchemy import Column
from sqlalchemy import String
from sqlalchemy import DateTime
from sqlalchemy import event
from sqlalchemy import ForeignKeyConstraint
from sqlalchemy import inspect
from sqlalchemy import Integer
from sqlalchemy import PrimaryKeyConstraint
from sqlalchemy import util
from sqlalchemy.orm import attributes
from sqlalchemy.orm import object_mapper
from sqlalchemy.orm import class_mapper
from sqlalchemy.orm import ColumnProperty
from sqlalchemy.orm.exc import UnmappedColumnError
from sqlalchemy.orm.relationships import RelationshipProperty

to_ignore = {'updated_at', 'created_at'}

def col_references_table(col, table):
    for fk in col.foreign_keys:
        if fk.references(table):
            return True
    return False


def _is_versioning_col(col):
    # if col.key in to_ignore:
    #     return True
    return "version_meta" in col.info


def _history_mapper(local_mapper):
    cls = local_mapper.class_

    if cls.__dict__.get("_history_mapper_configured", False):
        return

    cls._history_mapper_configured = True

    super_mapper = local_mapper.inherits
    polymorphic_on = None
    super_fks = []
    properties = util.OrderedDict()

    if super_mapper:
        super_history_mapper = super_mapper.class_.__history_mapper__
    else:
        super_history_mapper = None

    if (
        not super_mapper
        or local_mapper.local_table is not super_mapper.local_table
    ):
        version_meta = {"version_meta": True}  # add column.info to identify
        # columns specific to versioning

        history_table = local_mapper.local_table.to_metadata(
            local_mapper.local_table.metadata,
            name=local_mapper.local_table.name + "_history",
        )

        for orig_c, history_c in zip(
            local_mapper.local_table.c, history_table.c
        ):
            orig_c.info["history_copy"] = history_c
            history_c.unique = False
            history_c.default = history_c.server_default = None
            history_c.autoincrement = False

            if super_mapper and col_references_table(
                orig_c, super_mapper.local_table
            ):
                assert super_history_mapper is not None
                super_fks.append(
                    (
                        history_c.key,
                        list(super_history_mapper.local_table.primary_key)[0],
                    )
                )
            if orig_c is local_mapper.polymorphic_on:
                polymorphic_on = history_c

            orig_prop = local_mapper.get_property_by_column(orig_c)
            # carry over column re-mappings
            if (
                len(orig_prop.columns) > 1
                or orig_prop.columns[0].key != orig_prop.key
            ):
                properties[orig_prop.key] = tuple(
                    col.info["history_copy"] for col in orig_prop.columns
                )

        for const in list(history_table.constraints):
            if not isinstance(
                # const, (PrimaryKeyConstraint, ForeignKeyConstraint)
                # https://github.com/sqlalchemy/sqlalchemy/discussions/10227
                const, PrimaryKeyConstraint
            ):
                history_table.constraints.discard(const)

        # "version" stores the integer version id.  This column is
        # required.
        history_table.append_column(
            Column(
                "version",
                Integer,
                primary_key=True,
                autoincrement=False,
                info=version_meta,
            )
        )

        # "changed" column stores the UTC timestamp of when the
        # history row was created.
        # This column is optional and can be omitted.
        history_table.append_column(
            Column(
                "changed",
                DateTime,
                default=lambda: datetime.datetime.now(datetime.timezone.utc),
                info=version_meta,
            )
        )

        history_table.append_column(
            Column(
                "action_taken_by",
                Integer,
                default=None,
                info=version_meta,
            )
        )

        history_table.append_column(
            Column(
                "action_type",
                String(2),
                default=None,
                index=True,
                info=version_meta,
            )
        )

        if super_mapper:
            super_fks.append(
                ("version", super_history_mapper.local_table.c.version)
            )

        if super_fks:
            history_table.append_constraint(
                ForeignKeyConstraint(*zip(*super_fks))
            )

    else:
        history_table = None
        super_history_table = super_mapper.local_table.metadata.tables[
            super_mapper.local_table.name + "_history"
        ]

        # single table inheritance.  take any additional columns that may have
        # been added and add them to the history table.
        for column in local_mapper.local_table.c:
            if column.key not in super_history_table.c:
                col = Column(
                    column.name, column.type, nullable=column.nullable
                )
                super_history_table.append_column(col)

    if not super_mapper:
        local_mapper.local_table.append_column(
            Column("version", Integer, default=1, nullable=False),
            replace_existing=True,
        )
        local_mapper.add_property(
            "version", local_mapper.local_table.c.version
        )

        if cls.use_mapper_versioning:
            local_mapper.version_id_col = local_mapper.local_table.c.version

    # set the "active_history" flag
    # on column-mapped attributes so that the old version
    # of the info is always loaded (currently sets it on all attributes)
    for prop in local_mapper.iterate_properties:
        prop.active_history = True

    super_mapper = local_mapper.inherits

    if super_history_mapper:
        bases = (super_history_mapper.class_,)

        if history_table is not None:
            properties["changed"] = (history_table.c.changed,) + tuple(
                super_history_mapper.attrs.changed.columns
            )

    else:
        bases = local_mapper.base_mapper.class_.__bases__

    versioned_cls = type(
        "%sHistory" % cls.__name__,
        bases,
        {
            "_history_mapper_configured": True,
            "__table__": history_table,
            "__mapper_args__": dict(
                exclude_properties=to_ignore,
                inherits=super_history_mapper,
                polymorphic_identity=local_mapper.polymorphic_identity,
                polymorphic_on=polymorphic_on,
                properties=properties,
            ),
        },
    )

    cls.__history_mapper__ = versioned_cls.__mapper__


class Versioned:
    use_mapper_versioning = False
    """if True, also assign the version column to be tracked by the mapper"""

    __table_args__ = {"sqlite_autoincrement": True}
    """Use sqlite_autoincrement, to ensure unique integer values
    are used for new rows even for rows that have been deleted."""

    def __init_subclass__(cls) -> None:
        insp = inspect(cls, raiseerr=False)

        if insp is not None:
            _history_mapper(insp)
        else:

            @event.listens_for(cls, "after_mapper_constructed")
            def _mapper_constructed(mapper, class_):
                _history_mapper(mapper)

        super().__init_subclass__()

    def history_get_all(self, tz='America/New_York'):
        """
        Will return a list of history objects.
        Return is not queryable
        """
        return HistorySerializer().get_history_delta(self, timezone=tz)

    def history_search_in_this(self, kwargs):
        """
        https://stackoverflow.com/a/41309069
        usage like: db.session.get(DemoTestTable, 1).history_search_in_this({'priority':"high"})
        Returns a list, same as history_get_all()
        """
        # self.__history_mapper__.class_.query.filter(**kwargs).all()
        cls = self.__history_mapper__.class_
        qry = cls.query
        for attr, value in kwargs.items():
            qry = qry.filter(getattr(cls, attr) == value)

        return qry.all()


def versioned_objects(iter_):
    for obj in iter_:
        if hasattr(obj, "__history_mapper__") and not hasattr(obj, "ignore_me"):
            yield obj


def create_version(obj, session, deleted=False, new=False, updated=False, first=False):
    from flask_login import current_user
    if current_user and hasattr(current_user, "id"):
        updated_by = current_user.id
    else:
        updated_by = 1

    obj_mapper = object_mapper(obj)
    history_mapper = obj.__history_mapper__
    history_cls = history_mapper.class_

    obj_state = attributes.instance_state(obj)

    attr = {}

    obj_changed = False

    for om, hm in zip(
        obj_mapper.iterate_to_root(), history_mapper.iterate_to_root()
    ):
        if hm.single:
            continue

        for hist_col in hm.local_table.c:
            if _is_versioning_col(hist_col):
                continue

            obj_col = om.local_table.c[hist_col.key]

            # get the value of the
            # attribute based on the MapperProperty related to the
            # mapped column.  this will allow usage of MapperProperties
            # that have a different keyname than that of the mapped column.
            try:
                prop = obj_mapper.get_property_by_column(obj_col)
            except UnmappedColumnError:
                # in the case of single table inheritance, there may be
                # columns on the mapped table intended for the subclass only.
                # the "unmapped" status of the subclass column on the
                # base class is a feature of the declarative module.
                continue

            # expired object attributes and also deferred cols might not
            # be in the dict.  force it to load no matter what by
            # using getattr().
            if prop.key not in obj_state.dict:
                getattr(obj, prop.key)

            a, u, d = attributes.get_history(obj, prop.key)

            if first:
                if d:
                    attr[prop.key] = d[0]
                    obj_changed = True
                elif u:
                    attr[prop.key] = u[0]
                elif a:
                    # if the attribute had no value.
                    attr[prop.key] = a[0]
                    obj_changed = True
            else:
                if a:
                    attr[prop.key] = a[0]
                    obj_changed = True
                elif u:
                    attr[prop.key] = u[0]
                elif d:
                    attr[prop.key] = d[0]
                    obj_changed = True

    if not obj_changed:
        # not changed, but we have relationships.  OK
        # check those too
        for prop in obj_mapper.iterate_properties:
            if (
                isinstance(prop, RelationshipProperty)
                and attributes.get_history(
                    obj, prop.key, passive=attributes.PASSIVE_NO_INITIALIZE
                ).has_changes()
            ):
                for p in prop.local_columns:
                    if p.foreign_keys:
                        obj_changed = True
                        break
                if obj_changed is True:
                    break

    if not obj_changed and not deleted:
        return

    attr["action_taken_by"] = updated_by
    attr["action_type"] = "~" if updated else "-" if deleted else "+" if new else "?"
    if new:
        attr["version"] = 0
    else:
        attr["version"] = obj.version

    hist = history_cls()
    for key, value in attr.items():
        setattr(hist, key, value)
    session.add(hist)
    obj.version += 1


def versioned_session(session):
    @event.listens_for(session, "before_flush")
    def before_flush(session, flush_context, instances):
        # print("before")
        for obj in versioned_objects(session.dirty):
            if obj.version == 0:
                create_version(obj, session, updated=True, first=True)
                # print("1")
            create_version(obj, session, updated=True)
            # print("1.1")
        for obj in versioned_objects(session.deleted):
            create_version(obj, session, deleted=True)
            # print("2")

    @event.listens_for(session, "after_flush")
    def receive_after_flush(session, flush_context):
        # print("after")
        for obj in versioned_objects(session.new):
            create_version(obj, session, new=True)
            # print("3")


class HistorySerializer:
    """
    Takes a model object and outputs a list of dicts containing the full history of an item.
    Will output full initial item, then the diff from each change along
     with history date and user that made the change.
    """

    def __init__(self, convo_id=None, user="None"):
        self.user = user
        if convo_id:
            self.convo_id = convo_id
        else:
            self.convo_id = str(uuid.uuid4())

        self.pop_list = ['changed', 'action_taken_by', 'action_type', 'version', 'updated_at',
                         'created_at', 'datemodified']

    def utc_to_local(self, time_string, tz="America/New_York"):
        """
        Converts UTC to local based on user timezone.
        Used for emails only
        :param time_string: date/time in str format (2020-04-29 11:16:03.562353 or '2017-01-12T22:11:31+00:00')
        :param tz: timezone of user fed from front end (America/New_York)
        """
        try:
            if isinstance(time_string, str) and isinstance(tz, str) and time_string and tz:
                utctime = parse(time_string)
                if utctime.tzinfo is None or utctime.tzinfo.utcoffset(utctime) is None:
                    utctime = pytz.utc.localize(utctime)
                return utctime.astimezone(pytz.timezone(tz)).strftime("%m/%d/%Y %r")
            else:
                return None
        except Exception as e:
            return None

    def pair_iterable_for_delta_changes(self, iterable):
        """
        Pair the records so diff can be established.
        https://madil.in/going-through-historical-changes-with-django-simple-history/
        """
        if isinstance(iterable, Iterable):
            a, b = tee(iterable)
            next(b, None)
            return zip(a, b)
        else:
            return None

    def as_dict(self, item):
        result = {}
        for prop in class_mapper(item.__class__).iterate_properties:
            if isinstance(prop, ColumnProperty) and prop.key not in self.pop_list:
                result[prop.key] = getattr(item, prop.key)
        return result

    def diff_against(self, new_record, old_record):
        new_record = self.as_dict(new_record)
        old_record = self.as_dict(old_record)
        shared_keys = set(new_record.keys()).intersection(set(old_record.keys()))
        return {o: (new_record[o], old_record[o]) for o in shared_keys if new_record[o] != old_record[o]}

    def get_history_delta(self, the_object, timezone="America/New_York"):
        """
        Build the actual data structure with diffs from each history version
        :param the_object: the model object to get the history from
        """
        from app.models import Users
        # original_item_columns = the_object.__mapper__.column_attrs.keys()
        retrieved_users = {}
        the_item_history = the_object.__history_mapper__.class_.query.filter_by(id=the_object.id).all()

        if len(the_item_history) > 0:
            # add first history item so that all the subsequent diffs make sense.
            first_item = the_item_history[0]

            old_user = "System"
            # TODO - figure out how to return action_taken_by as an object
            if first_item.action_taken_by:
                if old := retrieved_users.get(first_item.action_taken_by):
                    old_user = old
                else:
                    old_user = Users.query.get(first_item.action_taken_by).fullname()
                    retrieved_users[first_item.action_taken_by] = old_user


            return_list = [{
                'history_date': self.utc_to_local(first_item.changed.strftime("%m/%d/%Y %r"), str(timezone)),
                'history_user': old_user,
                'changes': [{'field': key, 'old': None, 'new': val} for (key, val) \
                            in self.as_dict(first_item).items() if key not in self.pop_list]
            }]

            # loop each group of deltas to build return dict
            for record_pair in self.pair_iterable_for_delta_changes(the_item_history):
                old_record, new_record = record_pair
                delta = self.diff_against(new_record, old_record)

                new_user = "System"
                if new_record.action_taken_by:
                    if new := retrieved_users.get(first_item.action_taken_by):
                        new_user = new
                    else:
                        new_user = Users.query.get(first_item.action_taken_by).fullname()
                        retrieved_users[first_item.action_taken_by] = new_user

                return_list.append({
                    'history_date': self.utc_to_local(new_record.changed.strftime("%m/%d/%Y %r"), str(timezone)),
                    'history_user': new_user,
                    'changes': [{'field': k, 'old': v[1], 'new': v[0]} for k, v in delta.items() if
                                k not in self.pop_list]
                })

            # cycle through changes list and localize any datetimes.
            for each in return_list:
                for change in each['changes']:
                    for k, v in change.items():
                        if isinstance(v, datetime.datetime):
                            change[k] = self.utc_to_local(v.strftime("%m/%d/%Y %r"), str(timezone))

            return return_list
        else:
            return []
