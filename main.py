import click
from flask import Flask, abort, render_template, redirect, url_for, flash, request
from flask_bootstrap import Bootstrap5
from flask_login import UserMixin, login_user, LoginManager, current_user, logout_user, login_required
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFError
from sqlalchemy.orm import relationship, DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Integer, String, Text, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import os
from dotenv import load_dotenv
from forms import LoginForm, OrderForm, CSRFOnlyForm

# SUPER EXPLANATORY COMMENTS ARE MOSTLY FOR ME SINCE I JUST LEARNT A LOT OF THIS STUFF

# The CSRFOnlyForm does it so that you create your form, pass it in,
# create the hidden_tag which puts the CSRF token on the hidden part of the form
# then when you click something it submits the form with the CSRF token
# and if it is validated it will do the action associated with the form

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY")
Bootstrap5(app)

BALL_PRICE = 1
TEE_PRICE = 1
LEMONADE_PRICE = 1
ORDER_TIME = timedelta(minutes=20)
MY_TZ = ZoneInfo("America/Chicago")


# replaces all the utc timezone info with my timezone
@app.template_filter('central_time')
def central_time_filter(dt):
    if dt is None:
        return ""
    return dt.replace(tzinfo=timezone.utc).astimezone(MY_TZ)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

EMPLOYEE_PASSWORD_HASH = os.environ.get("EMPLOYEE_PASSWORD_HASH", "")


# Adds a new terminal command: "flask hash-password". It asks you to type a password
# (hiding the letters as you type, and asking you to type it twice to check for typos),
# then runs it through generate_password_hash - the same function used everywhere else
# in this file - and prints the resulting hash so you can copy it into EMPLOYEE_PASSWORD_HASH.
# This isn't a new way of hashing, just an easy way to run the normal one from the terminal.
@app.cli.command("hash-password")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
def hash_password(password):
    click.echo(generate_password_hash(password))


class Employee(UserMixin):
    id = "employee"


employee = Employee()


# user_loader function that well... loads users, but it looks slightly different since we only have one user
@login_manager.user_loader
def load_user(user_id):
    return employee if user_id == employee.id else None


class Base(DeclarativeBase):
    pass

db_uri = os.environ.get("DB_URI", "sqlite:///project.db")
# Replaces the db_uri with a postgresql one when we are having to use postgresql
if db_uri.startswith("postgres://"):
    db_uri = db_uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(model_class=Base)
db.init_app(app)

ORDER_STATUSES = ("pending", "in_progress", "completed")

# DB Tables

class Order(db.Model):
    __tablename__ = 'orders'
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True)
    hole_number: Mapped[int] = mapped_column(db.Integer)
    name: Mapped[str] = mapped_column(db.String)
    ball_qty: Mapped[int] = mapped_column(db.Integer, default=0)
    tee_qty: Mapped[int] = mapped_column(db.Integer, default=0)
    lemonade_qty: Mapped[int] = mapped_column(db.Integer, default=0)
    cost: Mapped[int] = mapped_column(db.Integer)
    status: Mapped[str] = mapped_column(db.String, default="pending")
    timestamp: Mapped[datetime] = mapped_column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class ShopStatus(db.Model):
    __tablename__ = 'shop_status'
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True)
    is_open: Mapped[bool] = mapped_column(db.Boolean, default=True)


# Fixes the data for when we have 2 different dbs because we have one for production too
def fix_data():
    inspector = inspect(db.engine)
    if 'orders' in inspector.get_table_names():
        columns = {col['name'] for col in inspector.get_columns('orders')}
        if 'status' not in columns:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE orders ADD COLUMN status VARCHAR DEFAULT 'pending'"))
        if 'lemonade_qty' not in columns:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE orders ADD COLUMN lemonade_qty INTEGER DEFAULT 0"))


with app.app_context():
    db.create_all()
    fix_data()


# Finds whether shop is open or closed
def open_or_closed():
    status = db.session.get(ShopStatus, 1)
    if status is None:
        status = ShopStatus(id=1, is_open=True)
        db.session.add(status)
        db.session.commit()
    return status


# when orders exceed 20 minutes, they are deleted
def delete_old_orders():
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - ORDER_TIME
    try:
        db.session.execute(db.delete(Order).where(Order.timestamp < cutoff))
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()


# Error handling which routes to error.html

@app.errorhandler(404)
def page_not_found(e):
    return render_template('error.html', code=404, message="That page doesn't exist."), 404


@app.errorhandler(500)
def internal_error(e):
    db.session.rollback()
    return render_template('error.html', code=500, message="Something went wrong on our end."), 500


@app.errorhandler(CSRFError)
def csrf_error(e):
    flash("Your form session expired. Please try again.")
    return redirect(request.referrer or url_for('index'))

# PAGES

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/about')
def about():
    return render_template('about.html')

# For logging in as employee
@app.route('/login', methods=['GET', 'POST'])
def login():
    # Has the same button, but the text changes, so you're going to the same route
    # even if you are authenticated and are rerouted to the admin page
    if current_user.is_authenticated:
        return redirect(url_for('orders'))
    form = LoginForm()
    if form.validate_on_submit():
        # Form checking to log in user using hashes for security
        if EMPLOYEE_PASSWORD_HASH and check_password_hash(EMPLOYEE_PASSWORD_HASH, form.password.data):
            login_user(employee)
            return redirect(url_for('orders'))
        flash("Incorrect password")
        # Restart login
        return redirect(url_for('login'))
    return render_template('login.html', form=form)

# For logging out as employee
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# Orders for employees
@app.route('/orders', methods=['GET', 'POST'])
@login_required
def orders():
    delete_old_orders()
    # Finds all the orders
    current_orders = db.session.execute(db.select(Order).order_by(Order.timestamp)).scalars().all()
    return render_template(
        'orders.html',
        current_orders=current_orders,
        shop_status=open_or_closed(),
        form=CSRFOnlyForm(),
    )


# When employees mark whether an order is completed or in progress, it is processed here and updates the page.
@app.route('/orders/<int:order_id>/status', methods=['POST'])
@login_required
def update_order_status(order_id):
    form = CSRFOnlyForm()
    if form.validate_on_submit():
        new_status = request.form.get('status')
        if new_status in ORDER_STATUSES:
            order_to_update = db.session.get(Order, order_id)
            if order_to_update is not None:
                try:
                    # updates order status
                    if new_status == "completed":
                        db.session.delete(order_to_update)
                    else:
                        order_to_update.status = new_status
                    db.session.commit()
                except SQLAlchemyError:
                    db.session.rollback()
                    flash("Couldn't update that order. Please try again.")
    return redirect(url_for('orders'))


# Can change whether we're taking orders.
@app.route('/shop-status', methods=['POST'])
@login_required
def toggle_shop_status():
    form = CSRFOnlyForm()
    if form.validate_on_submit():
        status = open_or_closed()
        # only 2 options so if you click the button it is now the opposite of what it was before you clicked it
        status.is_open = not status.is_open
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            flash("Couldn't update shop status. Please try again.")
    return redirect(url_for('orders'))

# For ordering golf balls
@app.route('/order', methods=['GET', 'POST'])
def order():
    shop_status = open_or_closed()
    if not shop_status.is_open:
        return render_template('order.html', closed=True)

    form = OrderForm()
    if form.validate_on_submit():
        ball_qty = form.ball_qty.data or 0
        tee_qty = form.tee_qty.data or 0
        lemonade_qty = form.lemonade_qty.data or 0
        # calculates cost to put in Order table
        cost = (
            ball_qty * BALL_PRICE
            + tee_qty * TEE_PRICE
            + lemonade_qty * LEMONADE_PRICE
        )
        new_order = Order(
            hole_number=form.hole_number.data,
            name=form.name.data,
            ball_qty=ball_qty,
            tee_qty=tee_qty,
            lemonade_qty=lemonade_qty,
            cost=cost,
        )
        try:
            db.session.add(new_order)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            flash("Something went wrong placing your order. Please try again.")
            return redirect(url_for('order'))
        flash(f"Order placed! Total cost: ${cost}. We'll bring your order out shortly.")
        return redirect(url_for('order'))
    return render_template(
        'order.html',
        form=form,
        closed=False,
        price_per_ball=BALL_PRICE,
        price_per_tee=TEE_PRICE,
        price_per_lemonade=LEMONADE_PRICE,
    )

if __name__ == '__main__':
    app.run(port=5001)
