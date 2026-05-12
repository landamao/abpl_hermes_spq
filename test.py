import os

# 获取 main.py 所在目录的绝对路径
script_dir = os.path.dirname(os.path.abspath(__file__))
# 向上两级到达 data 目录
data_dir = os.path.dirname(os.path.dirname(script_dir))
# 等价写法：data_dir = os.path.abspath(os.path.join(script_dir, '../..'))

print(data_dir)