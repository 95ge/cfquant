# -*- coding: utf-8 -*-
"""
Created on Fri Oct 14 21:16:19 2022

@author: Administrator
"""
import threading
import socket 
import os
import time
import json
import struct
import signal
import queue
import datetime
import importlib
import subprocess
import sys
from packaging import version

#运行需要的库
need_packge = {'psutil':{'pip_name':'psutil','version':'1.0.0'},
               'pandas':{'pip_name':'pandas','version':'0.0.1'},
               'orjson':{'pip_name':'orjson','version':'0.0.1'},
               'zmq':{'pip_name':'pyzmq','version':'0.0.1'},
               'websockets':{'pip_name':'websockets','version':'0.0.1'},
               'lz4':{'pip_name':'lz4','version':'0.0.1'},
               'cryptography':{'pip_name':'cryptography','version':'0.0.1'},
               'tabulate':{'pip_name':'tabulate','version':'0.0.1'},
               'hashlib':{'pip_name':'hashlib','version':'0.0.1'},
               'pandas_market_calendars':{'pip_name':'pandas_market_calendars','version':'latest'},
               'pytz':{'pip_name':'pytz','version':'0.0.0'}
               }


def ensure_modules_with_version(modules: dict):
    """
    - 确保指定模块及版本已安装或自动升级（使用清华源）。
    - 版本号中如果是latest，则每次都会去尝试更新到最新的版本，这样可以确保程序每次启动时都是用最新的库。
    - 版本号中如果是数字，如果当前安装的版本低于该版本，则会升级到最新版本，如果高于或等于则跳过。
    
    :param modules: dict，格式为：
        {
            "导入模块名": {
                "pip_name": "pip安装名",
                "version": "版本号(如2.2.0或latest)"
            }
        }
    """
    for import_name, meta in modules.items():
        pip_name = meta.get("pip_name", import_name)
        required_version = meta.get("version", "latest")

        try:
            mod = importlib.import_module(import_name)
            if required_version == "latest":
                print(f"[AutoInstall] 已安装 {import_name}，但指定为最新版本，将尝试升级...")
                raise ImportError("强制升级")
            else:
                # 获取已安装版本
                installed_version = getattr(mod, '__version__', None)
                if installed_version is None:
                    print(f"[AutoInstall] 警告：无法检测 {import_name} 的版本信息，尝试强制安装指定版本 {required_version}...")
                    raise ImportError()
                if version.parse(installed_version) < version.parse(required_version):
                    print(f"[AutoInstall] 检测到 {import_name} 当前版本为 {installed_version}，小于要求的 {required_version}，将自动升级...")
                    raise ImportError()
                else:
                    print(f"[AutoInstall] {import_name} 已安装，版本为 {installed_version}，满足要求")
        except ImportError:
            # 安装或升级
            install_target = pip_name if required_version == "latest" else "lastest"
            print(f"[AutoInstall] 正在安装/升级 {pip_name} → {required_version}...")
            try:
                subprocess.check_call([
                    sys.executable, "-m", "pip", "install", install_target,
                    "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"
                ])
                print(f"[AutoInstall] 成功安装 {pip_name} {required_version}")
            except Exception as e:
                print(f"[AutoInstall] 安装 {pip_name} 失败: {e}")

#先执行安装,再导入对应的库
ensure_modules_with_version(need_packge)




import pytz
import tabulate
import hashlib
import psutil
import pandas_market_calendars as mcal

id_code = 1
all_que = queue.Queue(maxsize=0)

def get_local_ip():
    """
    查询本机ip地址
    :return: ip
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    finally:
        s.close()
    return ip
def my_handler(signum, frame):
    print('程序退出')
    os._exit(0)

signal.signal(signal.SIGINT, my_handler)
dict_connect_info = {}#根据id_code存储连接方信息    

def send_msg(client,result):
    result['version'] = self_version
    result = json.dumps(result).encode('utf-8')    
    client.sendall(result)


def wait_accept(server):
    while True:
        try:
            client, address = server.accept()
            client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            start_thread(target = handle_connect,args=(client,address))
        except Exception as e: 
            time.sleep(1)
    server.shutdown(socket.SHUT_RDWR)
    close_con(server)
    
def start_thread(target,args):
    thp1 = threading.Thread(target=target,args=args)
    thp1.start()

log_que = queue.Queue()
log_list = []

def sys_show_on(data):
    '''
    日志显示
    '''
    log_list.append(data)
    if len(log_list) > 50:
        log_list.pop(0)
    log_que.put(data)
    # connect_show_list.append(data)
    # print(data)

def main_save_log():
    try:
        os.mkdir('log_data')
    except:
        pass
    while 1:
        data = log_que.get()
        with open('./log_data/%s_log.csv'%(time.strftime("%Y-%m-%d")),'a+',encoding='utf-8') as f:
            f.write(str(data)+'\n')
            
msg = '%s>>>>>>>[info] LTtx程序启动'%(time.strftime("%Y-%m-%d %H:%M:%S"))
threading.Thread(target = main_save_log).start()

def close_con(client):
    try:
        # 强制停止读写操作，确保 recv 不再阻塞
        client.shutdown(socket.SHUT_RDWR)
    except socket.error as e:
        pass
    finally:
        # 释放套接字资源
        client.close()


def handle_connect(client,address):
     global id_code
     while True:
         try:
            # 接收客户端发过来的数据 循环为这个客户端服务多次
            recv_data = client.recv(1024)
            sys_show_on("%s:收到客户端%s请求连接的消息：%s" %(get_str_time(),address,recv_data.decode("utf-8")))
            #print("%s:收到客户端%s请求连接的消息：%s" %(get_str_time(),address,recv_data.decode("utf-8")))
            dict_data = json.loads(recv_data)
            con_type = dict_data['con_type']
            con_tocken = dict_data['tocken']
            dict_data['加入时间'] = get_str_time()     
            dict_data['con'] = client
            if con_tocken != tocken:
                code = '-1'
                msg = '传入的tocken:%s不匹配,当前服务器版本%s'%(con_tocken,self_version)
                result = {'code':code,'msg':'服务器发来消息：%s'%(msg)}
                send_msg(client,result)
            elif con_type == 'put_mode':                           
                result = handle_connect_put(client,address,dict_data)
                C_que = queue.Queue(maxsize=0)
                C_que_push = queue.Queue(maxsize=0)
                start_thread(target = main_handle_client_que,args=(client, C_que, C_que_push))
                start_thread(target = main_push_data_que,args=(client, C_que_push))
                send_msg(client,result)
                start_thread(target = main_handle_msg_tx,args=(client,address,C_que,id_code)) 
            elif con_type == 'push_mode':
                who = dict_data['who']
                if '@' not in who:
                    who = [who]
                else:
                    who = who.split('@')
                pwd = dict_data['pwd']
                result = handle_connect_push(client,address,who,pwd,dict_data=dict_data)
                send_msg(client,result)
            elif con_type == 'file_mode':
                handle_connect_file(client,address,dict_data)
                close_con(client)
                break
            elif con_type == 'plus_mode':
                id_code = id_code + 1
                dict_data['id_code'] = id_code
                result = {'code':0,'msg':'plus mode连接成功','id_code':id_code}
                start_thread(target = main_handle_push_plus,args=(client,))
                dict_connect_info[id_code] = dict_data
                send_msg(client,result)
            elif con_type == 'check_version':
                from tx import txl
                tx1 = txl('a',2025,'test')
                version = tx1.version
                result = {'LTtx_lastest':version}
                send_msg(client,result)
            # 如果客户端发送的数据不为空那么就是需要服务
            else:
                result = '当前连接未通过'
                send_msg(client,result)
                close_con(client)
            break
         except Exception as e:
            try:
                result = '当前连接未通过>>>%s'%(str(e))
                sys_show_on(result)
                send_msg(client,result)
                close_con(client)
            except:
                break



def handle_connect_file(client,address,dict_data):
    file_mode = dict_data['file_mode']
    if file_mode == 'upload_file':
        file_name = dict_data['file_name']
        file_hash = dict_data['file_hash']
        file = open('./file_data/%s'%(file_name+'.tmp'),'wb')
        client.sendall(b'i am ok')
        file_data = client.recv(1024)
        while file_data:
            file.write(file_data)
            file_data = client.recv(1024)
        file.close()
        sys_show_on('%s文件接收完成'%(file_name))
        if os.path.isfile('./file_data/%s'%(file_name)):
            os.remove('./file_data/%s'%(file_name))
        os.rename('./file_data/%s'%(file_name + '.tmp'), './file_data/%s'%(file_name))
       
    elif file_mode == 'download_file':
        file_name = dict_data['file_name']
        hash_md5 = hashlib.md5()
        if os.path.isfile('./file_data/%s'%(file_name)):
            client.sendall('file exist'.encode())
            file = open('./file_data/%s'%(file_name), 'rb')
            file_data = file.read(1024)
            while file_data:
                client.sendall(file_data)
                file_data = file.read(1024)
            file.close()
            time.sleep(1)
            close_con(client)
        else:
            client.sendall('file does not exist'.encode())
    else:
        pass
    


def handle_put(var,data):
    que_put.put((var,data))
    return {'code':0,'msg':'put work down'}

que_put = queue.Queue()
def main_handle_put():
    file_path = os.path.join(os.path.dirname(__file__), 'data0.txt')
    while True:
        var,data = que_put.get()
        try:
            data = json.loads(data)
        except:
            pass
        dict_var[var] = data
        if que_put.qsize() > 50:
            while True:
                if  que_put.qsize() > 2:
                    try:
                        data = json.loads(data)
                    except:
                        pass
                    dict_var[var] = data
                else:
                    break
        with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(dict_var, f, ensure_ascii=False, indent=4)

def load_and_run(module_name: str, class_name: str, method_name: str):
    # 导入并 reload
    module = importlib.import_module(module_name)
    importlib.reload(module)

    # 判断类是否存在
    if not hasattr(module, class_name):
        print(f"模块中未找到类：{class_name}")
        return None

    cls1 = getattr(module, class_name)
    instance = cls1()  # 实例化类

    # 判断方法是否存在且可调用
    if hasattr(instance, method_name):
        method = getattr(instance, method_name)
        if callable(method):
            print('work here')
            return method()  # 调用并返回结果
        else:
            print(f"{method_name} 不是可调用对象")
    else:
        print(f"类 {class_name} 中无方法 {method_name}")



class SysTools:
    def judge_market_open(dict_data):
        '''
        判断开市时间
        '''
        exchange_code = dict_data['exchange_code']
        now = dict_data['now']
    
    def get_market_calendars(dict_data):
        '''
        返回一个交易日
        '''
        
    def is_market_open(exchange_code: str) -> bool:
        """检测上海交易所是否开盘"""
        # 获取交易所日历
        cal = mcal.get_calendar(exchange_code)
    
        # 根据交易所设置本地时区
        tz_map = {
            "XSHG": "Asia/Shanghai",  # A股（上交所）
            "XSHE": "Asia/Shanghai",  # A股（深交所）
            "XHKG": "Asia/Hong_Kong",  # 港股
            "XNYS": "America/New_York"  # 美股（纽交所）
        }
        tz = pytz.timezone(tz_map.get(exchange_code, "UTC"))
        now = datetime.datetime.now(tz)  # 带时区的当前时间
    
        # 1. 检查是否为交易日
        schedule = cal.schedule(start_date=now.date(), end_date=now.date())
        if schedule.empty:
            return False  # 非交易日（休市）
    
        # 2. 提取交易时段并统一时区
        market_open = schedule["market_open"].iloc[0].tz_convert(tz.zone)
        market_close = schedule["market_close"].iloc[0].tz_convert(tz.zone)
    
        # 3. 判断当前是否在交易时段内
        return market_open <= now <= market_close

def handle_sys_tools(dict_data):
    '''
    提供一些系统级功能函数
    '''
    tools = dict_data['tools']
    

def handle_get(var):
    if var in dict_var:
        return {'value':dict_var[var]}
    else:
        return {'value':None}
def get_str_time():
    '''
    返回2024-11-23 13:00:09数据格式
    '''
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())


def recv_data_from_tx(client):
    recv_bytes = client.recv(8,socket.MSG_WAITALL)
    bytes_len = struct.unpack("Q",recv_bytes)[0]
    recv_data = client.recv(bytes_len,socket.MSG_WAITALL)
    recv_data = json.loads(recv_data.decode('utf-8',errors='replace'))
    return recv_data

def recv_data_from_tx_fast(client):
    recv_bytes = client.recv(8,socket.MSG_WAITALL)
    bytes_len = struct.unpack("Q",recv_bytes)[0]
    recv_data = client.recv(bytes_len,socket.MSG_WAITALL)
    recv_data = recv_data.decode('utf-8',errors='replace')
    return recv_data

def send_data_to_client_fast(client,msg):
    msg = msg.encode('utf-8')
    data_len = len(msg)
    struct_bytes = struct.pack('Q', data_len)
    client.sendall(struct_bytes)
    client.sendall(msg)
        
def send_data_to_client(client,msg):
    msg=json.dumps(msg).encode('utf-8')
    data_len = len(msg)
    struct_bytes = struct.pack('Q', data_len)
    client.sendall(struct_bytes)    
    client.sendall(msg)
    # client.sendall(struct_bytes+msg)

def main_handle_push_plus(client):
    while True:
        recv_data = recv_data_from_tx_fast(client).rsplit(':who:',1)
        who = recv_data[1]
        if who in dict_client_push_group:
            if len(dict_client_push_group[who]['group']) == 0:
                pass
            else:
                dict_client_push_group[who]['que'].put((client,recv_data[0]))
    

def main_handle_msg_tx(client,address,C_que,id_code):
    sys_show_on(get_str_time()+':'+'客户端'+str(address)+'加入tx')
    while True:
        try:
            recv_data = recv_data_from_tx(client)
            C_que.put(recv_data)
        except Exception as e:
            try:
                close_con(client)            
                msg = 'TX客户端%s退出,退出原因%s'%(dict_client[id_code]['address'],str(e))
                sys_show_on(msg)
                del dict_client[id_code]
                del dict_connect_info[id_code]
                break
            except:
                pass
            break

def main_handle_client_que(client,C_que,C_que_push):
    while True:
        try:
            recv_data = C_que.get()
            func = recv_data['func']
            if func == 'push':
                who = recv_data['who']
                if who in dict_client_push_group:
                    if len(dict_client_push_group[who]['group']) == 0:
                        pass
                    else:
                        recv_data = recv_data['value']
                        dict_client_push_group[who]['que'].put((client,recv_data))
                else:
                    pass
            elif func == 'get':
                var = recv_data['value']
                result = handle_get(var)
                C_que_push.put(result)
            elif func == 'put':
                data = recv_data['value'][1]
                var = recv_data['value'][0]
                result = handle_put(var,data)
            elif func == 'list_append':
                data = recv_data['value'][1]
                var = recv_data['value'][0]
                result = handle_list_append(var,data)
            elif func == 'dict_change':
                value = recv_data['value'][2]
                data = recv_data['value'][1]
                var = recv_data['value'][0]
                result = handle_dict_change(var,data,value) 
            elif func == 'list_pop':
                data = recv_data['value'][1]
                var = recv_data['value'][0]
                result = handle_list_pop(var,data)
            elif func == 'list_remove':
                data = recv_data['value'][1]
                var = recv_data['value'][0]
                result = handle_list_remove(var,data)
            elif func == 'put_dataframe':
                data = recv_data['value'][1]
                var = recv_data['value'][0]
                result = handle_put_dataframe(var,data)
            elif func == 'get_dataframe':
                var = recv_data['value']
                result = handle_get_dataframe(var)
                C_que_push.put(result)
            elif func == 'get_dict_value':
                result = handle_get_dict_value(recv_data['value'][0],recv_data['value'][1])
                C_que_push.put(result)
            elif func == 'get_list_value':
                result = handle_get_list_value(recv_data['value'][0],recv_data['value'][1])
                C_que_push.put(result)
        except:
            pass


def handle_get_dict_value(var,key):
    if var in dict_var:
        if key in dict_var[var]:
            return {'value':dict_var[var][key]}
        else:
            return {'value':None}
    else:
        return {'value':None}

def handle_get_list_value(var,index):
    if var in dict_var:
        if abs(index) > len(dict_var[var]):
            return {'value':dict_var[var][index]}
        else:
            return {'value':None}
    else:
        return {'value':None}        

def handle_get_dataframe(var):
    '''
    处理get dataframe
    '''
    import pandas as pd
    if var in dict_df:
        try:
            df = pd.read_csv('./dataframe_data/%s.csv'%(var))
        except:
            df = pd.DataFrame()
    else:
        df = pd.DataFrame()
    
    return {'value':json.dumps(df.to_dict(orient='records'))}

dict_df = {}
def handle_put_dataframe(var,data):
    import pandas as pd
    try:
        df = pd.DataFrame(json.loads(data))
        df.to_csv('./dataframe_data/%s.csv'%(var),index=False)
        dict_df[var] = 1
        tem_dict = {'code':0,'msg':'success','value':{}}
    except Exception as e:
        tem_dict = {'code':-1,'msg':str(e)}
        print(tem_dict)
    return tem_dict


def handle_list_remove(var,data):
    global dict_var_on
    try:
        dict_var[var].remove(data)
        if dict_var_on == False:
            dict_var_on = True
    except:
        pass

def handle_list_pop(var,data):
    global dict_var_on
    try:
        data = int(data)
        dict_var[var].pop(data)
        if dict_var_on == False:
            dict_var_on = True
    except:
        pass

def handle_list_append(var,data):
    global dict_var_on
    try:
        dict_var[var].append(data)
        if dict_var_on == False:
            dict_var_on = True
    except:
        pass

def handle_dict_change(var,key,value):
    global dict_var_on
    # try:
    print(dict_var)
    # tem_dict = json.loads(dict_var[var])
    # tem_dict[key] = value
    dict_var[var][key] = value
    if dict_var_on == False:
        dict_var_on = True
    # except:
    #     pass

def main_push_data_que(client,C_que_push):
    while True:
        result = C_que_push.get()
        # print(result,'----')
        send_data_to_client(client,msg=json.dumps(result))
                
    
def handle_connect_put(con,address,dict_data):
    global id_code
    id_code = id_code + 1
    dict_data['id_code'] = id_code
    dict_client[id_code] = {'con':con,'address':address,'id_code':id_code,}
    # dict_data['con']
    dict_connect_info[id_code] = dict_data
    msg = '服务端发来信息：新连接加入成功'
    code = 0 
    result = {'code':code,'msg':msg,'id_code':id_code}
    return result

def main_heartbeat():
    '''
    客户端心跳维护子线程

    Returns
    -------
    None.

    '''
    recv_data = {1:1}
    while True:
        for who,value in dict_client_push_group.items():
            value['que'].put((1,recv_data))
        time.sleep(5)

def main_push_client(tem_que,client,id_code,who):
    while True:
        msg = tem_que.get()
        try:
            send_data_to_client(client, msg)
        except Exception as e:
            msg = '%s:有broadcast客户端%s退出,退出原因%s'%(get_str_time(),dict_client_push[id_code]['address'],str(e))
            sys_show_on(msg)
            close_con(client)
            try:
                del dict_connect_info[id_code]
                # print(1)
                del dict_client_que[client]
                # print(2)
                del dict_client_push[id_code]
                # print(3)
                dict_client_push_group[who]['group'].remove(client)                 
                # print(4)
            except Exception as e:
                pass
                print('删除连接出错',e,id_code)
            break
            
dict_client_que_id_code = {}#根据id_code存放队列，用这个来查找待推送的数据量
def handle_connect_push(con,address,who_list,pwd='520',dict_data={}):
    global id_code
    id_code = id_code + 1
    dict_client_push[id_code] = {'con':con,'address':address,'id_code':id_code}
    dict_data['con'] = con
    dict_connect_info[id_code] = dict_data
    for who in who_list:
        if who in dict_client_push_group:
            if pwd == dict_client_push_group[who]['pwd']:
                dict_client_push_group[who]['group'].append(con)
                msg = '服务端发来信息：欢迎加入%s信道,当前总信道连接数为:%s'%(who,len(dict_client_push_group[who]['group']))
                tem_que = queue.Queue()
                dict_client_que[con] = tem_que
                dict_client_que_id_code[id_code] = tem_que
                threading.Thread(target = main_push_client,args=(tem_que,con,id_code,who)).start()
                threading.Thread(target = main_txg_heartbeat,args=(con,)).start()
                code = 0
            else:
                msg = '服务端发来信息：当前信道%s已经存在，传入的密码:%s不正确，请重新传入密码'%(who,pwd)
                del dict_client_push[id_code]
                code = -1
        else:
            tem_que = queue.Queue()
            dict_client_que[con] = tem_que
            dict_client_que_id_code[id_code] = tem_que
            threading.Thread(target = main_push_client,args=(tem_que,con,id_code,who)).start()
            tem_que = queue.Queue(maxsize=0)
            dict_client_push_group[who] = {'group':[con],'pwd':pwd,'que':tem_que}
            thp0 = threading.Thread(target = main_push_queue,args=(tem_que,who))
            thp0.start()
            threading.Thread(target = main_txg_heartbeat,args=(con,)).start()
            msg = '服务端发来信息：新信道%s创建成功'%(who)
            code = 0
        result = {'code':code,'msg':msg}
    return result

def main_txg_heartbeat(client):
    '''
    处理txg的心跳
    '''
    while 1:
        try:
            client.recv(1,socket.MSG_WAITALL)
            # recv_data = json.loads(recv_data.decode('utf-8',errors='replace'))
        except:            
            break

def main_push_queue(que,who):
    sys_show_on('新信道%s子线程启动'%(who))
    while True:
        # try:
            client,recv_data = que.get()
            group_list = dict_client_push_group[who]['group']
            if len(group_list) ==0:
                sys_show_on('删除%s信道'%(who))
                del dict_client_push_group[who]
                break
            else:
                for i in group_list:
                    if i in dict_client_que:    
                        dict_client_que[i].put(recv_data)
                    else:
                        group_list.remove(i)
     


def main_test():
    while True:
        print('\n\r')
        a=input('输入要执行的python代码:\n\n')
        print('执行结果如下:\n\n')
        if a=='clear':
            os.system('clear')
        else:
            try:
                exec(a)
                print('\n')
            except Exception as e:
                print(e)

def load_dict_var():
    try:
        # 假设 data0.txt 和 LTtx_server.py 在同一目录
        config_path = os.path.join(os.path.dirname(__file__), 'data0.txt')
        
        # 尝试打开并读取 JSON 文件
        with open(config_path, 'r', encoding='utf-8') as f:
            dict_var = json.load(f)
           # print('Load dict_var success!')
    except FileNotFoundError:
        #print(f"Load Error: File not found at {config_path}")
        dict_var = {}
    except json.JSONDecodeError:
       # print("Load Error: File is not valid JSON")
        dict_var = {}
    except Exception as e:
      #  print('Load Error:', e)
        dict_var = {}
    
    return dict_var

def main_show():
    while True:
        table_data = []
        for who,value in dict_client_push_group.items():
            print(who,value['que'].qsize())
            tem_list = [who[:10],len(value['group']),value['que'].qsize(),'']
            table_data.append(tem_list)
        print('\033c', end='')

        print('#'*20,'服务器信息V5','#'*20)
        print('ip:%s'%(ip),' '*10,'port:%s'%(port),' '*10,'tocken:%s'%(tocken))
        
        print('#'*20,'当前LTtx状态','#'*20)
        print('当前TX连接数：%s                 当前TXG信道数'%(len(dict_client)),len(dict_client_push_group))
        
        print(tabulate.tabulate(table_data, headers=['信道名称', '当前连接数', '信道队列数据量','备注'], tablefmt='fancy_grid',stralign='wrap'))

        print('%sLTtx系统最新日志信息：'%(time.strftime('%Y-%m-%d %H:%M:%S',time.localtime())))
        print('#'*30)
        for i in connect_show_list:
            print(i)
            if len (connect_show_list) > 10:
                connect_show_list.remove(i)
        print('\n\r')
        print('#'*30)
        
        
        time.sleep(1)


def show_channel_list():
    table_data = []
    for channel in dict_client_push_group:
        tem_que_len = dict_client_push_group[channel]['que'].qsize()
        user_num = len(dict_client_push_group[channel]['group'])
        tem_list = [channel[:10],user_num,tem_que_len]
        table_data.append(tem_list)
    print(tabulate.tabulate(table_data, headers=['信道名称', '当前连接数', '信道队列数据量','备注'], tablefmt='fancy_grid',stralign='wrap'))

def show_push_client_qsize():
    '''
    打印每个客户端的待推送数据长度
    '''
    for i in dict_client_que:
        print(i,'>>>>',dict_client_que[i].qsize())

def channel_mange():
    while True:
        print('#'*20,'信道管理','#'*20)
        choice_dict = {'1----查看当前所有信道':show_channel_list,     
                       '2----查看所有连接待推送数据量':show_push_client_qsize,
                       '99----返回上一级':'',
                    }
        for i in choice_dict:
            print(i)
        cmd_dict = {}
        for i in choice_dict:
            cmd_dict[i.split('-')[0]] = choice_dict[i]
        cmd = input('输入指令:')
        if cmd == '99':            
            break                
        if cmd not in cmd_dict:
            print('当前指令不存在')
            continue
        print('【info指令运行结果】')
        cmd_dict[cmd]()    
        print('\n\r')

def show_connect_list():
    for id_code in dict_client:
        print(dict_client[id_code])


def close_connet_single():
    
    show_dict_connect_info()
    id_code = int(input('请选择要断开的id_code'))
    if id_code in dict_connect_info:
        con = dict_connect_info[id_code]['con']        
        client = con
        close_con(client)
        try:
            del dict_connect_info[id_code]
            # print(1)
            del dict_client_que[client]
            # print(2)
            del dict_client_push[id_code]
            if 'who' in dict_connect_info[id_code]:                
                # print(3)
                who = dict_connect_info[id_code]['who']
                dict_client_push_group[who]['group'].remove(client)                 
            # print(4)
        except Exception as e:
            pass
            print('删除连接出错',e,id_code)
    else:
        print('当前id_code不存在')

def connect_mange():
    while True:
        print('#'*20,'连接管理','#'*20)
        choice_dict = {'1----查看当前所有连接':show_connect_list,       
                       '2----断开单个连接':close_connet_single,
                       '99----返回上一级':'',
                    }
        for i in choice_dict:
            print(i)
        cmd_dict = {}
        for i in choice_dict:
            cmd_dict[i.split('-')[0]] = choice_dict[i]
        cmd = input('输入指令:')
        if cmd == '99':            
            break                
        if cmd not in cmd_dict:
            print('当前指令不存在')
            continue
        print('【info指令运行结果】')
        cmd_dict[cmd]()    
        print('\n\r')

def log_mange():
    print('#'*20,'日志管理','#'*20)
    
def reback():
    pass    


def show_system_log():
    for i in log_list:
        print(i)


def show_dict_connect_info():
    for i in dict_connect_info:
        tem_dict = {}
        if dict_connect_info[i]['con_type'] in ['push_mode','plus_mode']:
            id_code = i
            tem_dict['待推送数据量'] = dict_client_que_id_code[id_code].qsize()      
        tem_dict.update(dict_connect_info[i])
        print(i,':',tem_dict)

def query_id_code_info():
    while True:
        print('当前有的id_code：',list(dict_connect_info.keys()))
        id_code = int(input('请输入id_code(0-----返回):'))
        if id_code in dict_connect_info:
            i = id_code
            tem_dict = {}
            if dict_connect_info[i]['con_type'] in ['push_mode','plus_mode']:
                id_code = i
                tem_dict['待推送数据量'] = dict_client_que_id_code[id_code].qsize()      
            tem_dict.update(dict_connect_info[i])
            print(i,':',tem_dict)
        elif id_code == 0:
            break
        else:
            print('%sid_code不存在'%(id_code))

def index():
    while True:
        print('【LTtx系统管理面板首页】:')
        choice_dict = {'1----信道管理':channel_mange,
                       '2----日志管理':log_mange,
                       '3----连接管理':connect_mange,
                       '4----查看系统最近日志':show_system_log,
                       '5----查看所有连接信息':show_dict_connect_info,
                       '6----按id_code查看连接信息':query_id_code_info,
                       '99----返回':reback,
                       }
        cmd_dict = {}
        for i in choice_dict:
            cmd_dict[i.split('-')[0]] = choice_dict[i]
            print(i)
        cmd = input('输入指令:')
        if cmd == '99':            
            pass                
        if cmd not in cmd_dict:
            print('当前指令不存在')
            continue
        print('【info指令运行结果】')
        cmd_dict[cmd]()
        print('\n\r')
        
        
        


def main_control():
    '''
    控制面板
    '''
    index()
        


def make_dir():
    flod_list = ['file_data','dataframe_data']
    for i in flod_list:
        try:
            os.mkdir(i)
        except:
            pass

def main_save_dict_var():
    global dict_var_on, dict_var
    # 获取当前脚本所在目录，并构建文件路径
    file_path = os.path.join(os.path.dirname(__file__), 'data0.txt')

    while True:
        if dict_var_on:
            dict_var_on = False  # 重置标志
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(dict_var, f, ensure_ascii=False, indent=4)
            print(f"dict_var saved to {file_path}")
        time.sleep(60)  # 每 60 秒检查一次

            
def main_zmq_mode(zmq_xsub_port,zmq_xpub_port):
    import zmq
    context = zmq.Context()
    # 创建并绑定发布者套接字
    frontend = context.socket(zmq.XSUB)
    frontend.setsockopt(zmq.SNDHWM, 10000000)
    frontend.setsockopt(zmq.RCVHWM, 10000000)
    frontend.bind("tcp://*:%s"%(zmq_xsub_port))

    # 创建并绑定订阅者套接字
    backend = context.socket(zmq.XPUB)
    backend.setsockopt(zmq.SNDHWM, 10000000)
    backend.setsockopt(zmq.RCVHWM, 10000000)
    backend.bind("tcp://*:%s"%(zmq_xpub_port))
    print("tcp://*:%s"%(zmq_xpub_port))
    print('zmq启动成功')
    # 启动代理
    zmq.proxy(frontend, backend)

def load_config():
    tem_dict = {}
    config_path = os.path.join(os.path.dirname(__file__), 'Config.txt')
    with open(config_path, 'r', encoding='utf-8') as f:
        data = f.read().split('\n')
        for i in data:
            if len(i) > 0 and ' ' in i and ':' in i:
                key = i.split(' ')[0].split(':')[0]
                value = i.split(' ')[0].split(':')[1]
                tem_dict[key] = value
    return tem_dict

def tcp_port_open(host, port, timeout=0.3):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        return sock.connect_ex((host, int(port))) == 0
    except Exception:
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass

def main():
    global tocken,ip,port,self_version
    self_version = 'V7.2.7'
    update_time = '2025-09-04'
    import multiprocessing
    config = load_config()
    port = int(config['port'])
    tocken = config['token']
    ip = get_local_ip()
    if tcp_port_open('127.0.0.1', port):
        print('LTtx server port %s already listening, skip duplicate start.' % port)
        return
    #ZMQ的订阅端口
    zmq_xsub_port = config['zmq_port1']
    #ZMQ的发布端口
    zmq_xpub_port = config['zmq_port2']
    zmq_mode = config['zmq_mode']
    set_cpu = config['set_cpu']
    if zmq_mode == "True":
        p0 = multiprocessing.Process(target=main_zmq_mode,args=(zmq_xsub_port,zmq_xpub_port))
        p0.daemon = True
        p0.start()
        
    if set_cpu:        
        # 创建一个Process对象，代表当前进程
        p = psutil.Process(os.getpid())
        
        # 将当前进程的CPU亲和性设置为只运行最后一颗CPU上
        p.cpu_affinity([p.cpu_affinity()[-1]])

    recv_buffer_size = 1024*1024*100
    server = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, recv_buffer_size,)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.settimeout(5)
    server.bind(('0.0.0.0',port))
    server.listen(5)
    print('\n\r')
    print('#'*20,'服务器信息%s'%(self_version),'#'*20)
    print('#'*20,'更新日期%s'%(update_time),'#'*20)
    print('ip:%s'%(ip),' '*10,'port:%s'%(port),' '*10,'tocken:%s'%(tocken))
    # threading.Thread(target=main_show).start()
    threading.Thread(target = main_heartbeat).start()
    threading.Thread(target = main_save_dict_var).start()
    threading.Thread(target = main_handle_put).start()    
    wait_accept(server)

#配置
connect_show_list = []
dict_var_on = False
make_dir()
dict_client_que = {}
dict_client_push = {}
dict_client_push_group = {}
dict_client = {}
dict_client_status = {}
dict_var = load_dict_var()#保存云变量

if __name__ == '__main__':
    threading.Thread(target = main_control).start()
    main()
    # threading.Thread(target = main).start()















