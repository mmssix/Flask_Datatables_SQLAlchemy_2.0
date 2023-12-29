import os
from datatables import DataTable
from flask import Flask, request, render_template, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase, aliased


class Base(DeclarativeBase):
    pass


app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'app.db')
db = SQLAlchemy(model_class=Base)
db.init_app(app)


class Users(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True)
    first = db.Column(db.String(254))
    last = db.Column(db.String(254))

    def fullname(self):
        return f"{self.first} {self.last}"


class ChatAllowedUsers(db.Model):
    __tablename__ = "allowed_users"
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id'), nullable=False, index=True)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    assigned_to = db.relationship('Users', lazy='joined', foreign_keys=[assigned_to_id])


class Chats(db.Model):
    __tablename__ = "chats"
    id = db.Column(db.Integer, primary_key=True)
    chat_name = db.Column(db.String(254), index=True)
    allowed_users = db.relationship('ChatAllowedUsers', cascade="all,delete", lazy='joined')
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    created_by = db.relationship('Users', foreign_keys=[created_by_id])


with app.app_context():
    db.create_all()


@app.route("/")
def index():
    return render_template('datatables.html')


@app.route("/serverside_datatables_api")
def serverside_datatables_api():
    """
    Datatables API for the app homepage.
    :return:
    """

    # Handle general Search bar
    def perform_search(queryset, user_input):
        user_input = str(user_input)
        return queryset.filter(
            db.or_(
                Chats.chat_name.like('%' + user_input + '%'),
                Chats.created_by.has(db.or_(
                    Users.last.like('%' + user_input + '%'),
                    Users.first.like('%' + user_input + '%'),
                    Users.username.like('%' + user_input + '%'))),
                Chats.allowed_users.any(db.or_(
                    Users.last.like('%' + user_input + '%'),
                    Users.first.like('%' + user_input + '%'),
                    Users.username.like('%' + user_input + '%'))),
            ))

    # Handle individual column search
    def perform_column_search(model_column, queryset, user_input):
        if "Users.last" in str(model_column):
            chat1 = db.aliased(Chats)
            return queryset.join(Chats.created_by.of_type(chat1)).filter(db.or_(
                Users.last.like('%' + user_input + '%'),
                Users.first.like('%' + user_input + '%'),
                Users.username.like('%' + user_input + '%')))
        elif 'Chats.allowed_users' in str(model_column):
            sub = db.session.scalars(db.select(ChatAllowedUsers.chat_id).join(Users). \
                                     filter(db.or_(Users.last.like('%' + user_input + '%'),
                                                   Users.first.like('%' + user_input + '%'),
                                                   Users.username.like('%' + user_input + '%'))).distinct())
            return queryset.filter(Chats.id.in_(sub))
        else:
            return queryset.filter(model_column.like("%" + user_input + "%"))

    colvals = [
        "id",
        "chat_name",
        "created_by", # <--Yes, this works in 1.4. In the JSON sent to the browser it returns a dict of the user object.
        ('created_by_name', 'created_by.last', lambda i: f"{i.first[0]}.{i.last}"),
        ('created_by_name2', 'created_by.first', lambda i: f"{i.first[0]}.{i.last}"),
        ("allowed_users", "allowed_users", lambda i: '/'.join([f'{x.assigned_to.fullname()}' for x in i.allowed_users])),
    ]

    base = db.session.query(Chats). \
        outerjoin(ChatAllowedUsers).group_by(Chats)

    ids = [1, 2]
    table = DataTable(request.args, Chats, base.filter(db.or_(
        ChatAllowedUsers.assigned_to_id.in_(ids),
        Chats.created_by_id.in_(ids))), colvals)

    table.searchable(lambda queryset, user_input: perform_search(queryset, user_input))
    table.searchable_column(
        lambda model_column, queryset, user_input:
        perform_column_search(model_column, queryset, user_input)
    )

    ret = table.json()
    return jsonify(table.json())
