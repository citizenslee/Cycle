from flask import Blueprint

bp_schedule= Blueprint('schedule', __name__, url_prefix='/schedule')

from . import schedule_config
from . import calendar



