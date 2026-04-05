import sys
sys.path.append('/Users/anshulagarwal/Desktop/Projects/wms-tool/api-server-flask')
from api.models import Warehouse
try:
    print(Warehouse.get_all())
except Exception as e:
    import traceback
    traceback.print_exc()
