from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, IntegerField, SubmitField
from wtforms.validators import DataRequired, NumberRange, Optional


class LoginForm(FlaskForm):
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Log In")


class OrderForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired()])
    hole_number = IntegerField("Hole Number", validators=[DataRequired(), NumberRange(min=1, max=18)])
    ball_qty = IntegerField("Golf Balls", validators=[Optional(), NumberRange(min=0)], default=0)
    tee_qty = IntegerField("Tees", validators=[Optional(), NumberRange(min=0)], default=0)
    snack_qty = IntegerField("Snacks", validators=[Optional(), NumberRange(min=0)], default=0)
    submit = SubmitField("Place Order")

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators=extra_validators):
            return False
        if not ((self.ball_qty.data or 0) + (self.tee_qty.data or 0) + (self.snack_qty.data or 0)):
            self.ball_qty.errors.append("Order at least one item.")
            return False
        return True
