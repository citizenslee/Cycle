from flask import Blueprint


bp_vendor = Blueprint('vendor', __name__, url_prefix='/v')


from . import outsourcing_manager

