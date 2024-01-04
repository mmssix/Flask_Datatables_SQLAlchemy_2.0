"""
This file holds the abstraction for the base model class.  It handles switching certain columns types for
mysql vs pysqlite, plus adds some basic add-on properties to each model (to_dict, get_or_create, etc).
"""
from dt_project import app, db
from sqlalchemy import func, text, Text, inspect
from sqlalchemy.sql import ClauseElement
from sqlalchemy.schema import FetchedValue
from sqlalchemy.dialects.mysql import LONGTEXT

# This handles the needs of mysql/sqlite for longtext type columns
# https://github.com/sqlalchemy/sqlalchemy/issues/4443
text_type = Text().with_variant(LONGTEXT(), "mysql")

class AbstractBase(db.Model):

    __abstract__ = True
    model_properties = {}

    created_at = db.Column(db.TIMESTAMP)
    updated_at = db.Column(db.TIMESTAMP)

    def __repr__(self):
        return str(getattr(self, "name", self.id))

    @property
    def to_dict(self):
        ret = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        return {k:v for k,v in ret.items() if k != "password_hash"}

    # # https://stackoverflow.com/a/27951648
    # def serialize(self):
    #     return {c: getattr(self, c) for c in inspect(self).attrs.keys()}
    #
    # @staticmethod
    # def serialize_list(l):
    #     return [m.serialize() for m in l]

    # def save_to_db(self) -> None:
    #     """
    #     Usage like:
    #         store = StoreModel(name='name')
    #         store.save_to_db()
    #     :return:
    #     """
    #     db.session.add(self)
    #     db.session.commit()
    #
    # def delete_from_db(self) -> None:
    #     db.session.delete(self)
    #     db.session.commit()

    @classmethod
    def get_or_create(model, defaults=None, **kwargs):
        """
        Will get an existing item, or create a new one.
        Slower because it searches for an existing item first.  This is good to ensure table integrity.

        Use like:
            user, created = SatUsers.get_or_create(
                user_id=current_user.id,
                defaults={
                    'user_level': 'Admin',
                    'types_allowed': 'DEGROWTH,GOVT,SPLIT,911,BILLING,SECURITY,DECOM'
                }
            )
            db.session.commit()

        :param defaults:
        :param kwargs:
        :return:
        """

        instance = db.session.query(model).filter_by(**kwargs).one_or_none()
        if instance:
            return instance, False
        else:
            params = {k: v for k, v in kwargs.items() if not isinstance(v, ClauseElement)}
            if defaults:
                defaults = {k: v for k, v in defaults.items() if k in [x.key for x in inspect(model).attrs]}
                params.update(defaults or {})
            instance = model(**params)
            try:
                db.session.add(instance)
                db.session.commit()
            except Exception:
                db.session.rollback()
                instance = db.session.query(model).filter_by(**kwargs).one()
                return instance, False
            else:
                return instance, True

    @classmethod
    def update_or_create(model, defaults={}, **kwargs):
        """
        Will find and update an existing item, or create a new one.
        Use like:
            kciuser, created = KciTrbTypes.update_or_create(
                user_id=user.id,
                defaults={
                    'userlevel': ul,
                    'trb_types_allowed': old_user.iloc[0].trb_types_allowed
                }
            )
        :param defaults:
        :param kwargs:
        :return:
        """
        defaults = {k:v for k,v in defaults.items() if k != 'id'}
        instance = db.session.query(model).filter_by(**kwargs).one_or_none()
        params = {k: v for k, v in kwargs.items() if not isinstance(v, ClauseElement)}
        if defaults:
            defaults = {k: v for k, v in defaults.items() if k in [x.key for x in inspect(model).attrs]}
            params.update(defaults or {})

        if instance:
            try:
                for key, value in params.items():
                    setattr(instance, key, value)

                db.session.merge(instance)
                db.session.commit()
            except Exception:
                db.session.rollback()
                instance = db.session.query(model).filter_by(**kwargs).one()
                return instance, False
            else:
                return instance, False
        else:
            instance = model(**params)
            try:
                db.session.add(instance)
                db.session.commit()
            except Exception:
                db.session.rollback()
                return None, False
            else:
                return instance, True
