#orders_route.py
from flask import Blueprint, render_template
from apps.tools.auth import login_required, permission_required


bp_orders = Blueprint('orders', __name__, url_prefix='/orders')

@bp_orders.route('/dashboard')
@permission_required('SA','GA','HA','HP','DA','DH','SE','PA')
def orders():
    return render_template("orders/dashboard.html")

from . import orders_index
from . import report
from . import task_type
from . import orders_list
from . import dispatch
from . import transfer
from . import outsourcing
from . import view_orders_timeline
from . import complete
from . import evaluate