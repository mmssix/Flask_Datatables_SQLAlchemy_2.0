import os
from datetime import datetime
from datatables import DataTable
from flask import Flask, request, render_template, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase, aliased
from sqlalchemy import event
from dateutil.parser import parse
import json


class Base(DeclarativeBase):
    pass


app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'app.db')
db = SQLAlchemy(model_class=Base)
db.init_app(app)

from base import AbstractBase
from history_meta import Versioned


class Users(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True)
    first = db.Column(db.String(254))
    last = db.Column(db.String(254))

    def shortname(self):
        return f"{self.first} {self.last}"

    def get_all_subordinates(self):
        users = Users.query.with_entities(Users.id, Users.username, Users.first, Users.last).filter(Users.id.in_([2]))
        all_subordinates = set(users)
        return all_subordinates


with app.app_context():
    current_user = db.session.query(Users).filter(Users.id == 1).first()

print(current_user)


class WaitProjectAssignedTo(db.Model):
    __tablename__ = "wait_projects_assigned"
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('wait_projects.id'), nullable=False, index=True)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    assigned_to = db.relationship('Users', lazy='joined', foreign_keys=[assigned_to_id])


class WaitTasksAssignedTo(db.Model):
    __tablename__ = "wait_tasks_assigned"
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('wait_tasks.id'), nullable=False, index=True)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    assigned_to = db.relationship('Users', foreign_keys=[assigned_to_id])


class WaitTasksLogs(AbstractBase):
    __tablename__ = "wait_tasks_logs"
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('wait_tasks.id'), nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    created_by = db.relationship('Users', foreign_keys=[created_by_id])
    desc = db.Column(db.Text)
    log_followers = db.Column(db.String(2000))

    def serialize(self):
        return {
            'created_at': self.created_at,
            'desc': self.desc,
            'task_id': self.task_id,
            'id': self.id,
            'log_followers': self.log_followers,
            'created_by': f"{self.created_by.first[0]}.{self.created_by.last}"
        }


class WaitProjects(Versioned, AbstractBase):
    __tablename__ = "wait_projects"
    id = db.Column(db.Integer, primary_key=True)
    project_num = db.Column(db.String(20), index=True)
    short_desc = db.Column(db.String(254))
    goal = db.Column(db.String(100))
    long_desc = db.Column(db.Text)
    status = db.Column(db.String(25), default='New')
    project_type = db.Column(db.String(100))
    for_group = db.Column(db.String(100))
    requested_completion = db.Column(db.DATE, nullable=True)
    priority = db.Column(db.String(100))
    assigned_to = db.relationship('WaitProjectAssignedTo', cascade="all,delete")
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    created_by = db.relationship('Users', foreign_keys=[created_by_id])
    related_actions = db.Column(db.String(254))

    def serialize(self):
        ret = self.to_dict
        ret['tasks'] = [x.serialize() for x in self.tasks]
        ret['created_by'] = f"{self.created_by.first[0]}.{self.created_by.last}"
        ret['assigned_to'] = [{'id': x.assigned_to.id, 'text': x.assigned_to.fullname()} for x in self.assigned_to]
        return ret

    # def serialize_tasks(self):
    #     return ', '.join([x.assigned_to.fullname for x in self.tasks])

    def __repr__(self):
        return f"{self.project_num}:{self.id}"

    def __str__(self):
        return self.project_num


@event.listens_for(WaitProjects, 'after_insert')
def after_insert_listener(mapper, connection, target):
    if not target.project_num:
        if len(str(target.id)) < 5:
            difference = 5 - len(str(target.id))
            uid = f"P{str(datetime.today().year)[2:4]}-{''.join(['0'] * difference)}{target.id}"
        else:
            uid = f"P{str(datetime.today().year)[2:4]}-{target.id}"

        target_table = WaitProjects.__table__
        connection.execute(
            target_table.update().
            where(target_table.c.id == target.id).
            values(project_num=uid)
        )


class WaitTasks(Versioned, AbstractBase):
    __tablename__ = "wait_tasks"
    id = db.Column(db.Integer, primary_key=True)
    task_num = db.Column(db.String(20))
    short_desc = db.Column(db.String(254))
    status = db.Column(db.String(25), default='New')
    target_completion = db.Column(db.DATE, nullable=True)
    assigned_to = db.relationship('WaitTasksAssignedTo', cascade="all,delete")
    long_desc = db.Column(db.Text)
    priority = db.Column(db.String(100))
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    created_by = db.relationship('Users', foreign_keys=[created_by_id])
    project_id = db.Column(db.Integer, db.ForeignKey('wait_projects.id'), nullable=False, index=True)
    logs = db.relationship('WaitTasksLogs', cascade="all,delete", backref="task")
    related_actions = db.Column(db.Text)

    def serialize(self):
        ret = self.to_dict
        ret['project_num'] = self.project.project_num
        ret['created_by'] = f"{self.created_by.first[0]}.{self.created_by.last}"
        ret['logs'] = [x.serialize() for x in self.logs]
        ret['assigned_to'] = [
            {'id': x.assigned_to.id, 'text': x.assigned_to.fullname(), 'short_name': x.assigned_to.shortname()} for x in
            self.assigned_to]
        return ret

    def serialize_assigned(self):
        return ', '.join([x.assigned_to.last for x in self.assigned_to])

    def __repr__(self):
        return f"{self.task_num}:{self.id}"

    def __str__(self):
        return self.task_num


WaitProjects.tasks = db.relationship('WaitTasks', cascade="all,delete", backref="project", lazy='dynamic', )


@event.listens_for(WaitTasks, 'after_insert')
def after_insert_listener(mapper, connection, target):
    if not target.task_num:
        if len(str(target.id)) < 5:
            difference = 5 - len(str(target.id))
            uid = f"T{str(datetime.today().year)[2:4]}-{''.join(['0'] * difference)}{target.id}"
        else:
            uid = f"T{str(datetime.today().year)[2:4]}-{target.id}"

        target_table = WaitTasks.__table__
        connection.execute(
            target_table.update().
            where(target_table.c.id == target.id).
            values(task_num=uid)
        )


class WaitProjectTypeSelections(db.Model):
    __tablename__ = "wait_projecttype_selections"
    id = db.Column(db.Integer, primary_key=True)
    group_name = db.Column(db.String(30))
    selection_text = db.Column(db.String(30))
    order = db.Column(db.Integer, default=0)

    @classmethod
    def json(cls):
        ret = {}
        for x in db.session.query(cls).order_by(cls.group_name.asc(), cls.order.asc()).all():
            if not ret.get(x.group_name):
                ret[x.group_name] = [x.selection_text]
            else:
                ret[x.group_name].append(x.selection_text)

        return ret

    def __repr__(self):
        return f'{self.group_name} - {self.selection_text}'

    def __str__(self):
        return f'{self.group_name} - {self.selection_text}'


with app.app_context():
    db.create_all()


@app.route("/")
def index():
    return render_template('datatables.html', direct_reports_count=1)

@app.route("/js")
def js():
    return send_from_directory("templates", "index.js")


def local_to_utc(time_obj, tz='America/New_York'):
    if isinstance(time_obj, str):
        time_obj = parse(time_obj)

    timezone = pytz.timezone(tz)
    local_time = timezone.localize(time_obj)
    converted_to_utc = local_time.astimezone(pytz.utc)
    return converted_to_utc.replace(microsecond=0)


@app.route("/serverside_datatables_api")
def serverside_datatables_api():
    """
    Datatables API for the app homepage.
    :return:
    """

    def perform_search(queryset, user_input):
        user_input = str(user_input)
        return queryset.filter(
            db.or_(
                WaitProjects.project_num.like('%' + user_input + '%'),
                WaitProjects.status.like('%' + user_input + '%'),
                WaitProjects.short_desc.like('%' + user_input + '%'),
                WaitProjects.goal.like('%' + user_input + '%'),
                WaitProjects.project_type.like('%' + user_input + '%'),
                WaitProjects.for_group.like('%' + user_input + '%'),
                WaitProjects.created_by.has(db.or_(
                    Users.last.like('%' + user_input + '%'),
                    Users.first.like('%' + user_input + '%'),
                    Users.username.like('%' + user_input + '%'))),
                WaitProjects.assigned_to.any(db.or_(
                    Users.last.like('%' + user_input + '%'),
                    Users.first.like('%' + user_input + '%'),
                    Users.username.like('%' + user_input + '%'))),
                WaitProjects.tasks.any(db.or_(
                    WaitTasks.task_num.like('%' + user_input + '%'),
                    WaitTasks.short_desc.like('%' + user_input + '%')
                ))
            ))

    def perform_column_search(model_column, queryset, user_input):
        if "Users.last" in str(model_column):
            return queryset.join(WaitProjects.created_by, aliased=True).filter(db.or_(
                Users.last.like('%' + user_input + '%'),
                Users.first.like('%' + user_input + '%'),
                Users.username.like('%' + user_input + '%')))
        elif 'created_at' in str(model_column):
            dates = user_input.split("<>")
            start = local_to_utc(dates[0].strip(), request.values.get("tz", 'EST'))
            end = local_to_utc(dates[1].strip(), request.values.get("tz", 'EST'))
            return queryset.filter(
                db.and_(WaitProjects.created_at >= start, WaitProjects.created_at <= end))
        elif 'WaitProjects.assigned_to' in str(model_column):
            sub = db.session.scalars(db.select(WaitProjectAssignedTo.project_id).join(Users). \
                                     filter(db.or_(Users.last.like('%' + user_input + '%'),
                                                   Users.first.like('%' + user_input + '%'),
                                                   Users.username.like('%' + user_input + '%'))).distinct())
            return queryset.filter(WaitProjects.id.in_(sub))
        elif 'WaitProjects.priority' in str(model_column):
            return queryset.filter(model_column == user_input)
        elif 'WaitProjects.status' in str(model_column) and user_input in ['allopen', 'allclosed']:
            if user_input == 'allopen':
                return queryset.filter(~WaitProjects.status.in_(['Completed', 'Cancelled']))
            elif user_input == 'allclosed':
                return queryset.filter(WaitProjects.status.in_(['Completed', 'Cancelled']))
        else:
            return queryset.filter(model_column.like("%" + user_input + "%"))

    colvals = [
        "id",
        "project_num",
        "status",
        "created_at",
        "created_by",
        "priority",
        ('created_by_name', 'created_by.last', lambda i: f"{i.first[0]}.{i.last}"),
        "short_desc",
        # ("tasks", "tasks", lambda i: [x.serialize() for x in i.tasks]),
        ("assigned_to", "assigned_to", lambda i: '/'.join([f'{x.assigned_to.shortname()}' for x in i.assigned_to])),
    ]

    # For getting the data from the right place in case of report or normal page load.
    if request.values.get("type", None) == 'report':
        data = json.loads(request.values.get("data", "[]"))
    else:
        data = request.args

    base = db.session.query(WaitProjects). \
        outerjoin(WaitProjects.assigned_to). \
        outerjoin(WaitProjects.tasks). \
        outerjoin(WaitTasksAssignedTo).group_by(WaitProjects)
    if not any([val for (key, val) in request.args.to_dict().items() if '[search][value]' in key]):
        base = base.filter(~WaitProjects.status.in_(['Completed', 'Cancelled']))

    if request.values.get("whos", None) == 'reports':
        my_sphere_all = [x.id for x in current_user.get_all_subordinates() if x.id != current_user.id]
        table = DataTable(data, WaitProjects, base.filter(db.or_(
            WaitProjectAssignedTo.assigned_to_id.in_(my_sphere_all),
            WaitProjects.created_by_id.in_(my_sphere_all),
            WaitTasks.assigned_to.any(WaitTasksAssignedTo.assigned_to_id.in_(my_sphere_all)),
            WaitTasks.created_by_id.in_(my_sphere_all))), colvals)
    elif request.values.get("whos", None) == 'mine':
        table = DataTable(data, WaitProjects, base.filter(db.or_(
            WaitProjects.assigned_to.any(WaitProjectAssignedTo.assigned_to_id == current_user.id),
            WaitProjects.created_by_id == current_user.id,
            WaitTasks.assigned_to.any(WaitTasksAssignedTo.assigned_to_id == current_user.id),
            WaitProjects.tasks.any(WaitTasks.created_by_id == current_user.id))), colvals)
    else:
        my_sphere_all = [x.id for x in current_user.get_all_subordinates()]
        my_sphere_all.append(current_user.id)
        table = DataTable(data, WaitProjects, base.filter(db.or_(
            WaitProjectAssignedTo.assigned_to_id.in_(my_sphere_all),
            WaitProjects.created_by_id.in_(my_sphere_all),
            WaitTasks.assigned_to.any(WaitTasksAssignedTo.assigned_to_id.in_(my_sphere_all)),
            WaitTasks.created_by_id.in_(my_sphere_all))), colvals)

    table.searchable(lambda queryset, user_input: perform_search(queryset, user_input))
    table.searchable_column(
        lambda model_column, queryset, user_input:
        perform_column_search(model_column, queryset, user_input)
    )

    # If requesting a report
    if request.values.get("type", None) == 'report':
        return table.return_report("project_export", request.values.get("tz", "America/New_York"))

    ret = table.json()
    return jsonify(ret)
