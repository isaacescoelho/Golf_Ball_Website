from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, IntegerField, SubmitField
from wtforms.validators import DataRequired, NumberRange, Optional


class LoginForm(FlaskForm):
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Log In")


# For post routes that don't actually have any real user info to validate ie just flipping a bool
class CSRFOnlyForm(FlaskForm):
    pass


class OrderForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired()])
    hole_number = IntegerField("Hole Number", validators=[DataRequired(), NumberRange(min=1, max=18)])
    ball_qty = IntegerField("Golf Balls", validators=[Optional(), NumberRange(min=0, max=50)], default=0)
    tee_qty = IntegerField("Tees", validators=[Optional(), NumberRange(min=0, max=50)], default=0)
    lemonade_qty = IntegerField("Lemonade", validators=[Optional(), NumberRange(min=0, max=50)], default=0)
    submit = SubmitField("Place Order")

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators=extra_validators):
            return False
        if not (
            (self.ball_qty.data or 0)
            + (self.tee_qty.data or 0)
            + (self.lemonade_qty.data or 0)
        ):
            self.ball_qty.errors.append("Order at least one item.")
            return False
        return True
