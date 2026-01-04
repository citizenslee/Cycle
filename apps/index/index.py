from flask import Blueprint, render_template


bp_index = Blueprint('index',__name__)


# 首页
@bp_index.route("/")
def index():
    return render_template("index.html")
