from flask import Flask, abort, render_template, redirect, url_for, flash, request
from flask_bootstrap import Bootstrap5
from flask_login import UserMixin, login_user, LoginManager, current_user, logout_user, login_required
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFError
from sqlalchemy.orm import relationship, DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Integer, String, Text
from sqlalchemy.exc import SQLAlchemyError
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import os
from dotenv import load_dotenv
from forms import LoginForm, OrderForm

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

@login_manager.user_loader
def load_user(user_id):
    return db.get_or_404(User, user_id)


class Base(DeclarativeBase):
    pass
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DB_URI")
db = SQLAlchemy(model_class=Base)
db.init_app(app)

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True)
    password: Mapped[str] = mapped_column(db.String)

class Order(db.Model):
    __tablename__ = 'orders'
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True)
    hole_number: Mapped[int] = mapped_column(db.Integer)
    name: Mapped[str] = mapped_column(db.String)
    ball_qty: Mapped[int] = mapped_column(db.Integer, default=0)
    tee_qty: Mapped[int] = mapped_column(db.Integer, default=0)
    snack_qty: Mapped[int] = mapped_column(db.Integer, default=0)
    cost: Mapped[int] = mapped_column(db.Integer)
    timestamp: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()


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
        user = db.session.execute(db.select(User)).scalars().first()
        if user and check_password_hash(user.password, form.password.data):
            login_user(user)
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
    return render_template('orders.html', current_orders=current_orders)

# For ordering golf balls
@app.route('/order', methods=['GET', 'POST'])
def order():
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
        price_per_ball=BALL_PRICE,
        price_per_tee=TEE_PRICE,
        price_per_snack=SNACK_PRICE,
    )

if __name__ == '__main__':
    app.run(port=5002, debug=True)