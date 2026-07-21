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

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY")
Bootstrap5(app)

BALL_PRICE = 1
TEE_PRICE = 1
SNACK_PRICE = 2
ORDER_TIME = timedelta(minutes=20)
MY_TZ = ZoneInfo("America/Chicago")


@app.template_filter('central_time')
def central_time_filter(dt):
    if dt is None:
        return ""
    return dt.replace(tzinfo=timezone.utc).astimezone(MY_TZ)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

EMPLOYEE_PASSWORD_HASH = os.environ.get("EMPLOYEE_PASSWORD_HASH", "")


@app.cli.command("hash-password")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
def hash_password(password):
    """Print a hash to store in EMPLOYEE_PASSWORD_HASH."""
    click.echo(generate_password_hash(password))


class Employee(UserMixin):
    id = "employee"


employee = Employee()


@login_manager.user_loader
def load_user(user_id):
    return employee if user_id == employee.id else None


class Base(DeclarativeBase):
    pass

db_uri = os.environ.get("DB_URI", "sqlite:///project.db")
if db_uri.startswith("postgres://"):
    # Render (and some other providers) hand out "postgres://" URIs, but
    # SQLAlchemy 2.x only accepts the "postgresql://" scheme.
    db_uri = db_uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(model_class=Base)
db.init_app(app)

ORDER_STATUSES = ("pending", "in_progress", "completed")


class Order(db.Model):
    __tablename__ = 'orders'
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True)
    hole_number: Mapped[int] = mapped_column(db.Integer)
    name: Mapped[str] = mapped_column(db.String)
    ball_qty: Mapped[int] = mapped_column(db.Integer, default=0)
    tee_qty: Mapped[int] = mapped_column(db.Integer, default=0)
    snack_qty: Mapped[int] = mapped_column(db.Integer, default=0)
    cost: Mapped[int] = mapped_column(db.Integer)
    status: Mapped[str] = mapped_column(db.String, default="pending")
    timestamp: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.utcnow)


class ShopStatus(db.Model):
    __tablename__ = 'shop_status'
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True)
    is_open: Mapped[bool] = mapped_column(db.Boolean, default=True)


def run_migrations():
    """Add columns that were introduced after the tables already existed in a deployed db."""
    inspector = inspect(db.engine)
    if 'orders' in inspector.get_table_names():
        columns = {col['name'] for col in inspector.get_columns('orders')}
        if 'status' not in columns:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE orders ADD COLUMN status VARCHAR DEFAULT 'pending'"))


with app.app_context():
    db.create_all()
    run_migrations()


def get_shop_status():
    status = db.session.get(ShopStatus, 1)
    if status is None:
        status = ShopStatus(id=1, is_open=True)
        db.session.add(status)
        db.session.commit()
    return status


def purge_expired_orders():
    cutoff = datetime.utcnow() - ORDER_TIME
    try:
        db.session.execute(db.delete(Order).where(Order.timestamp < cutoff))
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()


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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/about')
def about():
    return render_template('about.html')

# For logging in as employee
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('orders'))
    form = LoginForm()
    if form.validate_on_submit():
        if EMPLOYEE_PASSWORD_HASH and check_password_hash(EMPLOYEE_PASSWORD_HASH, form.password.data):
            login_user(employee)
            return redirect(url_for('orders'))
        flash("Incorrect password")
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
    purge_expired_orders()
    current_orders = db.session.execute(db.select(Order).order_by(Order.timestamp)).scalars().all()
    return render_template(
        'orders.html',
        current_orders=current_orders,
        shop_status=get_shop_status(),
        form=CSRFOnlyForm(),
    )


# Employees mark an order in-progress or completed
@app.route('/orders/<int:order_id>/status', methods=['POST'])
@login_required
def update_order_status(order_id):
    form = CSRFOnlyForm()
    if form.validate_on_submit():
        new_status = request.form.get('status')
        if new_status in ORDER_STATUSES:
            order_to_update = db.session.get(Order, order_id)
            if order_to_update is not None:
                order_to_update.status = new_status
                try:
                    db.session.commit()
                except SQLAlchemyError:
                    db.session.rollback()
                    flash("Couldn't update that order. Please try again.")
    return redirect(url_for('orders'))


# Employees flip whether we're currently taking orders
@app.route('/shop-status', methods=['POST'])
@login_required
def toggle_shop_status():
    form = CSRFOnlyForm()
    if form.validate_on_submit():
        status = get_shop_status()
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
    shop_status = get_shop_status()
    if not shop_status.is_open:
        return render_template('order.html', closed=True)

    form = OrderForm()
    if form.validate_on_submit():
        ball_qty = form.ball_qty.data or 0
        tee_qty = form.tee_qty.data or 0
        snack_qty = form.snack_qty.data or 0
        cost = ball_qty * BALL_PRICE + tee_qty * TEE_PRICE + snack_qty * SNACK_PRICE
        new_order = Order(
            hole_number=form.hole_number.data,
            name=form.name.data,
            ball_qty=ball_qty,
            tee_qty=tee_qty,
            snack_qty=snack_qty,
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
        price_per_snack=SNACK_PRICE,
    )

if __name__ == '__main__':
    app.run(port=5002)
