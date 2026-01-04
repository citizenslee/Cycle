# orders_index.py 工单管理首页
from flask import  render_template
from .route import bp_orders
from apps.tools.auth import permission_required




@bp_orders.route('/dashboard_index')
@permission_required('SA','GA','HA','HP','DA','DH')
def orders_index():
    return render_template("orders/dashboard_index.html")