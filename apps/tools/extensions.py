# extensions.py
from flask_sqlalchemy import SQLAlchemy

# 这里只创建对象，不绑定 app
db = SQLAlchemy()