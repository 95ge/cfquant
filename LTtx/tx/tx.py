# -*- coding: utf-8 -*-
"""
Created on Thu Sep 22 11:09:51 2022

@author: Administrator
"""
import socket
import threading
import json
import queue
import struct
import time
import os
import hashlib
import random
import datetime
import sys
import subprocess
import importlib
import pandas as pd



class txl:
    def __init__(self,ip,port,tocken,show=True,check_version=False,loss_callback=None):
        '''
        ip:服务器IP，
        port:服务器端口,
        tocken:认证秘钥，任意字符串
        show:是否输出日志信息，默认为输出日志
        check_version:检查版本，如果有新版本将会拉取最新的版本，但需要手动重启一次主程序，谨慎使用
        loss_callback:(待开发)在运行过程中，如果和服务端发生断网时的回调函数，传入后有助于处理连接断开时的处理动作
        
        '''                
        self.run_on = True
        self.orjson_on = None
        self.channel_list = False
        self.sys_print_on = show
        self.clean_day = None
        self.id = time.strftime("%Y%m%d%H%M%S")+'_'+self.create_channel(5)
        self.log_que = queue.Queue()
        self.mkdir('tx_log')
        msg = '包引入成功'
        self.save_log(msg)             
        self.loss_callback = loss_callback
        self.ip = ip
        self.port = port
        self.tocken = tocken
        self.start_tx_on = False
        self.txg = False        
        self.init_txg = False#初始化txg
        self.__judge_python_version()
        self.txg_running = False
        self.__tx = False
        self.__tx_plus = False
        self.push_count = 0
        self.timeout = 2
        self.heartbeat = 1
        self.tx_que_plus = queue.Queue(maxsize=0)
        self.tx_running = False
        self.file_tx = None
        #ZMQ模式
        self.__ZMQ = None
        self.__ZMQ_broadcast = None
        self.__txg_heartbeat_on = True#通信系统Push模式心跳检测线程状态
        self.__txg_heartbeat_time = time.time()
        self.version = '8.0.1'
        self.__version__ = self.version
        self.check_version_on = check_version        
        self.dict_TradeDay = {}        
        self.check_version()
        self.current_file = sys.modules[__name__].__file__ #当前文件名
        self.current_dir = os.path.dirname(os.path.abspath(self.current_file))#当前目录
        self.local_ip = self.get_local_ip()
        self.__version__msg = '更新于2026-07-07'    
        self.txg_dict = {}#存储txg对象        
        msg = '通信系统V%s加载成功,Have fun!当前版本更新于%s'%(self.__version__,self.__version__msg)
        self.sys_print(msg)
        self.server2 = False#判断服务器是不是新版本,看是否要用批量发送
        self.start()
        self.td_df = pd.DataFrame()#存放交易日期数据，如果没有调用则不会产生数据
        self.pre_TradeDay = {'now_date':''}#存放前一个交易日
        self.d_push_tx = False
    
    def start(self,):
        '''
        启动对应的组件
        '''
        threading.Thread(target = self.__main_log).start()   
    
    
    def auto_import(self,package_name, import_name=None):        
        import_name = import_name or package_name
        try:
            self.orjson_on = True
            return importlib.import_module(import_name)
        except ImportError:
            self.sys_price(f"[TxLink自动安装] 缺少依赖 {package_name}，正在安装...请不要退出，安装完成后程序将正常运行")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
                self.orjson_on = True
                return importlib.import_module(import_name)            
            except:
                self.sys_price('TxLink自动安装orjson模块失败，采用json模块，若要体验高性能，请手动pip install orjson后重试')
                import json
                self.orjson_on = False
                return json
    
        
    def __judge_python_version(self):
        '''
        python版本判断
            -对于3.7以下的版本，用queue.Queue和普通的json
            -对于3.7以上的版本，用deque加速
        '''
        if sys.version_info >= (3, 8):
            try:                
                self.json = self.auto_import('orjson')
                data = self.json.dumps('abc')                                
                if isinstance(data, bytes):#二次验证导包的情况
                    msg = '采用orjson进行数据交互'
                    self.orjson_on = True
                else:
                    msg = '采用json进行数据交互'
                    self.orjson_on = False                
                self.save_log(msg,)                            
            except Exception as e:
                msg = '自动引入orjson出错>>>%s，采用json进行数据交互'%(e)
                self.save_log(msg,)
                self.json = json   
                self.orjson_on = False
        else:
            msg = 'python版本小于3.8，采用json进行数据交互'
            self.save_log(msg,)
            self.json = json
            self.orjson_on = False
        if sys.version_info >= (3, 7):
            msg = 'python版本大于3.7，采用SimpleQueue进行数据传输'
            self.Q = queue.SimpleQueue()            
            self.tx_que = queue.SimpleQueue()
            self.save_log(msg)
        else:
            msg = 'python版本大于3.7，采用Queue进行数据传输'
            self.Q = queue.Queue()
            self.tx_que = queue.Queue()
            self.save_log(msg)
            
    def clean_log(self):
        '''
        清理30天前的日志
        '''
        if self.clean_day != self.get_nowdate():            
            try:
                file_list = sorted(os.listdir('./tx_log'))
                if len(file_list) > 30:
                    for file in file_list[:30]:
                        file_name = './tx_log/'+file
                        self.delete_file(file_name)
            except Exception as e:
                msg = '日志自动清楚报错了>>>>>为了不影响使用体验，请查看一下原因>>>>%s'%(e)
                self.sys_print(msg,show_force=True)
            self.clean_day = self.get_nowdate()
    def delete_file(self,file_name):
        msg = '删除tx运行日志%s'%(file_name)
        os.remove(file_name)
        self.sys_print(msg,show_force=True)
    
    

    def save_log(self,msg,):
        self.log_que.put((self.id,msg))

    def __main_log(self):
        self.clean_log()
        while self.run_on:
            try:
                data = str(self.log_que.get())+'\n'
                if self.log_que.qsize() > 100:         
                    self.clean_log()
                    for i in range(100):
                        data = data + self.log_que.get() +'\n'
                with open('./tx_log/%s.log'%(self.get_nowdate()),'a+',encoding='utf-8') as f:
                    f.write(data)
            except:#过滤掉日志记录出错
                #直接跳过日志记录，不影响主程序
                pass

    def check_version(self,):
        '''
        检查本地客户端版本是不是最新的
        '''
        if self.check_version_on:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM) 
            client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8192*100)
            client.connect(('pc.zltnet.top',2099)) 
            tem_dict = {'con_type':'check_version',
                        'tocken':'LTtx',
                        }
            client.sendall(json.dumps(tem_dict).encode('utf-8'))
            server_msg = client.recv(1024).decode()
            if server_msg['LTtx_lastest'] != self.__version__:
                self.sys_print('从LTtx官网获取最新tx.py')
                self.__get_lastest_file()
                self.sys_print('最新版本获取完成，程序2秒后重启')
                time.sleep(2)
                os._exit(1)
            else:
                self.sys_print('当前版本已经是最新')
                
    def update_tx_version(self):
        '''
        更新客户端到最新版本
        
        '''
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM) 
        client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8192*100)
        client.connect(('pc.zltnet.top',2099)) 
        tem_dict = {'con_type':'check_version',
                    'tocken':'LTtx',
                    }
        client.sendall(json.dumps(tem_dict).encode('utf-8'))
        server_msg = json.loads(client.recv(1024).decode())
        if server_msg['LTtx_lastest'] != self.__version__:
            self.sys_print('从LTtx官网获取最新tx.py')
            self.__get_lastest_file()
            self.sys_print('最新版本获取完成，程序2秒后重启')
            time.sleep(2)
            os._exit(1)
        else:
            self.sys_print('当前版本已经是最新')    
    
    def sys_print(self,data,show_force=False):
        msg = '%sLTtx[info]>>>>:%s,'%(self.get_nowtime(),data)
        if self.sys_print_on or show_force:            
            print(msg)
        self.save_log(msg)

    def send_file(self,file_name,show_on=True):
        '''
        将本地文件上传至数据中心

        Parameters
        ----------
        file_name : TYPE
            文件路径，通常为./data/file.txt.
        show_on : TYPE, optional
            是否Print进度，默认开启. The default is True.

        Returns
        -------
        code int.
        返回0表示成功，其他表示错误，参见msg
        msg string
        提示信息

        '''
        if os.path.isfile(file_name):
            if show_on:
                self.sys_print('识别到文件存在')
                self.sys_print(file_name)
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM) 
            client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8192*100)
            client.connect((self.ip,self.port)) 
            hash_md5 = hashlib.md5()
            with open(file_name, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            file_hash = hash_md5.hexdigest()
            tem_dict = {'con_type':'file_mode',
                        'tocken':self.tocken,
                        'file_name':file_name.rsplit('/',1)[-1],
                        'file_hash':file_hash,
                        'file_mode':'upload_file',
                        }
            client.sendall(json.dumps(tem_dict).encode('utf-8'))
            server_msg = client.recv(1024).decode()
            if server_msg == 'i am ok':
                t1 = time.time()
                file = open(file_name, 'rb')
                file_data = file.read(1024)
                while file_data:
                    client.send(file_data)
                    file_data = file.read(1024)
                file.close()
                # client.send(b'file send finish')
                # client.recv(1024).decode()
                client.close()
                if show_on:
                    self.sys_print('file send done! usetime:%ss'%(round(time.time()-t1,6)))
            else:
                self.sys_print('服务端拒绝了本次文件传输请求')
        else:
            self.sys_print('文件不存在,请重新传入,当前收到的文件名:')
            self.sys_print(file_name)
    
    def __get_lastest_file(self,file_name='tx.py',file_path='./',show_on=False):
        '''
        从服务端下载文件

        Parameters
        ----------
        file_name : TYPE
            要下载的文件名.
        file_path : TYPE, optional
            文件保存路径，不存在的路径将会被创建. The default is './'.
        show_on : TYPE, optional
            是否Print进度，默认开启. The default is True.
        Returns
        -------
        code int.
        返回0表示成功，其他表示错误，参见msg
        msg string
        提示信息

        '''
        file_path = self.current_dir
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM) 
        client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8192*100)
        client.connect(('pc.zltnet.top',2099)) 
        tem_dict = {'con_type':'file_mode',
                    'tocken':'LTtx',
                    'file_name':file_name,
                    'file_mode':'download_file',
                    }
        client.sendall(json.dumps(tem_dict).encode('utf-8'))
        server_msg = client.recv(1024).decode()
        if server_msg == 'file exist':
            t1 = time.time()
            file = open(file_path+file_name+'.tmp','wb')
            file_data = client.recv(1024)
            while file_data:
                file.write(file_data)
                file_data = client.recv(1024)
               
            file.close()
            if os.path.isfile(file_path+file_name):
                os.remove(file_path+file_name)
            os.rename(file_path+file_name+ '.tmp', file_path+file_name)
            code = 0
            msg = '%s文件接收完成,用时%ss'%(file_name,round(time.time()-t1,6))
            if show_on:
                print(code,msg)
            return code,msg
        else:
            code = -1
            msg = '服务端该文件不存在,请先上传'
            print(code,msg)
            return code,msg
    
    
    def recv_file(self,file_name,file_path='./',show_on=False):
        '''
        从服务端下载文件

        Parameters
        ----------
        file_name : TYPE
            要下载的文件名.
        file_path : TYPE, optional
            文件保存路径，不存在的路径将会被创建. The default is './'.
        show_on : TYPE, optional
            是否Print进度，默认开启. The default is True.
        Returns
        -------
        code int.
        返回0表示成功，其他表示错误，参见msg
        msg string
        提示信息

        '''
        if file_path[-1] != '/':
            file_path = file_path + '/'
        if os.path.isdir(file_path):
            pass
        else:
            self.sys_print(('文件路径不存在，自动创建该路径'))
            try:
                os.mkdir(file_path)
            except Exception as e:
                raise TypeError('文件路径自动创建失败,失败原因：%s'%(e))
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM) 
        client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8192*100)
        client.connect((self.ip,self.port)) 
        tem_dict = {'con_type':'file_mode',
                    'tocken':self.tocken,
                    'file_name':file_name,
                    'file_mode':'download_file',
                    }
        client.sendall(json.dumps(tem_dict).encode('utf-8'))
        server_msg = client.recv(1024).decode()
        if server_msg == 'file exist':
            t1 = time.time()
            file = open(file_path+file_name+'.tmp','wb')
            file_data = client.recv(1024)
            while file_data:
                file.write(file_data)
                file_data = client.recv(1024)
            file.close()
            code = 0
            msg = ('%s文件接收完成,文件MD5检验通过'%(file_name))
            if os.path.isfile(file_path+file_name):
                os.remove(file_path+file_name)
            os.rename(file_path+file_name+ '.tmp', file_path+file_name)
            code = 0
            msg = '%s文件接收完成,,用时%ss'%(file_name,round(time.time()-t1,6))
            if show_on:
                print(code,msg)
            return code,msg
        else:
            code = -1
            msg = '服务端该文件不存在,请先上传'
            self.sys_print((code,msg))
            return code,msg
    
    def start_tx(self,mode=None):
        '''
        - 开启数据推送功能，开启后可以使用get,put,push等函数
        - 如果要订阅数据，通过start_txg进行开启订阅，即可收到对应的数据
        '''
        if not self.run_on:
            msg = '识别到此前已经close过txl，重新运行self.run_on'
            self.sys_print(msg,show_force=True)
            self.run_on = True
        if not mode:
            self.tx_running = True
        while self.run_on:
            try:
                msg = 'start_tx正在连接(%s,%s)LTtx服务器,请稍后'%(self.ip,self.port)
                self.sys_print(msg,show_force=True)
                if self.__tx == False:
                    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM) 
                    client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8192*100)
                    # 设置立即发送（关闭 Nagle 算法，降低延迟）
                    client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    client.connect((self.ip,self.port))                    
                    tem_dict = {'con_type':'put_mode','tocken':self.tocken,
                                'local_ip':self.local_ip,
                                'current_file':self.current_file,'current_dir':self.current_dir,                                
                                }
                    self.sys_print(tem_dict)
                    client.sendall(json.dumps(tem_dict).encode('utf-8'))
                    if self.recv_msg_start_tx(client):
                        self.__tx = client
                        t0 = threading.Thread(target=self.main_tx_que)
                        t0.start()
                        thp0 = threading.Thread(target = self.start_tx_hearbeat)
                        thp0.start()
                        msg = 'start_tx连接成功,have fun'
                        self.sys_print(msg,show_force=True)
                        break
                    else:
                        self.close_connection(self.__tx)
                        self.__tx = False 
                else:
                    code = -1
                    msg = '请勿重复连接tx'
                    result = {'code':code,'msg':msg}
                    return result
            except Exception as e:
                msg = '服务端未启动,将在1秒后继续尝试start_tx,%s'%(e)
                self.sys_print(msg,show_force=True)
                time.sleep(1)
    
    def start_plus(self,):
        '''
        开启高性能式，该模式打开后可以使用push_plus函数，推送数据的延迟和效率会更高
        '''
        if not self.run_on:
            msg = '识别到此前已经close过txl，重新运行self.run_on'
            self.sys_print(msg,show_force=True)
        while self.run_on:
            try:
                msg = (self.get_nowtime(),'start_flash正在连接(%s,%s)LTtx服务器,请稍后'%(self.ip,self.port))
                self.sys_print(msg)
                if self.__tx_plus == False:
                    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM) 
                    client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8192*100)
                    client.connect((self.ip,self.port))
                    self.__tx_plus = client
                    tem_dict = {'con_type':'plus_mode','tocken':self.tocken,
                                'local_ip':self.local_ip,
                                'current_file':self.current_file,'current_dir':self.current_dir,
                                }
                    self.__tx_plus.sendall(json.dumps(tem_dict).encode('utf-8'))
                    if self.recv_msg_start_tx(client):
                        t0 = threading.Thread(target=self.main_tx_que_plus)
                        t0.start()
                        thp0 = threading.Thread(target = self.start_tx_hearbeat_plus)
                        thp0.start()
                        break
                    else:
                        self.close_connection(self.__tx_plus)
                        self.__tx_plus = False 
                else:
                    code = -1
                    msg = '请勿重复连接'
                    result = {'code':code,'msg':msg}
                    self.sys_print(result)
                    return result
                
            except Exception as e:
                if type(e) == ConnectionRefusedError:
                    msg = (self.get_nowtime(),'服务端未启动,将在1秒后继续尝试start_plus')
                    self.sys_print(msg)
                msg = (self.get_nowtime(),str(e))
                self.sys_print(msg)
                time.sleep(1)

    def start_txg(self,channel_list,pwd=''):
        '''
        - 订阅数据，多个频道用@进行连接，比如test@lttx5表示同时订阅两个频道的消息，
        - 对应的数据都放在Q这个队列中，可以通过下方txl.Q.get()进行获取，txl这里指你实例化以后的对象
        用法示例：
        tx1 = txl('192.168.1.65',2049,'test')
        tx1.start_txg('test@lttx5')
        while True:
            data = tx1.Q.get().split('|')   #消息通过“|”进行切割，前面为key，后面为value
            print(data)#这里出来的是一个列表
            #下方即可做相应的数据处理
        '''
        if not self.tx_running:
            self.start_tx()#启动tx，确保心跳正确
        if not self.run_on:
            msg = '识别到此前已经close过txl，重新运行self.run_on'
            self.sys_print(msg,show_force=True)
        while self.run_on:
            try:
                if self.init_txg==False:
                    self.channel_list = channel_list
                    for who in self.channel_list.split('@'):
                        if len(who) == 0:
                            continue
                        self.__connect_txg(who,pwd=pwd)
                    if self.txg != False:
                        break
                else:
                    code = -1
                    msg = '请勿重复连接txg'
                    result = {'code':code,'msg':msg}
                    self.sys_print(result)
                    return result
            except Exception as e:
                if type(e) == ConnectionRefusedError:
                    msg = (self.get_nowtime(),'服务端未启动,将在1秒后继续尝试start_txg')
                    self.sys_print(msg)
                    time.sleep(1)
        
    def __re_start_txg(self,channel_list,pwd=''):
        '''
        服务重连
        '''
        if not self.run_on:
            msg = '识别到此前已经close过txl，重新运行self.run_on'
            self.sys_print(msg,show_force=True)
        while self.run_on:
            try:
                if self.init_txg==False:
                    msg = '通过start_tx的心跳包进行重连'
                    self.sys_print(msg,show_force=True)
                    self.channel_list = channel_list
                    for who in self.channel_list.split('@'):
                        if len(who) == 0:
                            continue
                        self.__connect_txg(who,pwd=pwd)
                    if self.txg != False:
                        break
                else:
                    code = -1
                    msg = '请勿重复连接txg'
                    result = {'code':code,'msg':msg}
                    self.sys_price(result)
                    return result
            except Exception as e:
                if type(e) == ConnectionRefusedError:
                    msg = (self.get_nowtime(),'服务端未启动,将在1秒后继续尝试start_txg')
                    self.sys_print(msg)
                    time.sleep(1)
    
    
    def __connect_txg(self,who,pwd=''):
        '''
        连接txg
        '''
        while self.run_on:            
            if who in self.txg_dict and self.txg_dict[who]['txg_running']:
                self.sys_print((self.get_nowtime(),'订阅频道%s失败，该频道已经存在'%(who)))
                return
            try:
                msg = '正在订阅%s频道'%(who)
                self.sys_print(msg)
                client = socket.socket(socket.AF_INET, socket.SOCK_STREAM) 
                client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024*1024*100)
                self.txg_running = True
                client.connect((self.ip,self.port,))
                self.channel_pwd = pwd
                tem_dict = {'con_type':'push_mode','who':who,'pwd':pwd,'tocken':self.tocken,
                            'client_version':2,
                            'local_ip':self.local_ip,
                            'current_file':self.current_file,'current_dir':self.current_dir,
                            }                
                client.send(json.dumps(tem_dict).encode('utf-8'))
                if self.recv_msg_start_txg(client,timeout=1) == True:                           
                    if who not in self.txg_dict:
                        self.txg = client
                        self.txg_dict[who] = {'con':client,'txg_running':True}
                        msg = 'start_txg连接成功，订阅频道%s'%(who)
                        self.sys_print(msg,show_force=True)
                        self.__start_thread(target = self.recv_msg_broadcast, args = (who,client,pwd))
                        self.__start_thread(target = self.main_broadcast_heartbeat,args=(client, who, pwd))
                        break
                    else:
                        if not self.txg_dict[who]['txg_running']:
                            self.txg = client
                            msg = 'start_txg连接成功，订阅频道%s'%(who)
                            self.txg_dict[who]['con'] = client
                            self.txg_dict[who]['txg_running'] = True
                            self.sys_print(msg,show_force=True)
                            self.__start_thread(target = self.recv_msg_broadcast, args = (who,client,pwd))
                            self.__start_thread(target = self.main_broadcast_heartbeat,args=(client, who, pwd))
                            break
                        else:
                            msg = '由于%s已经存在，本次连接主动断开'%(who)
                            self.sys_print(msg)
                            self.close_connection(client,name=msg)
                            break
                else:
                    msg = (who,'start_txg连接失败，没有收到正常的数据,可能是认证不通过,请确认您的token是否正确')
                    self.sys_print(msg)
                    break
            except Exception as e:
                msg = '在订阅%s连接txg时服务器出错了>>>>>%s,将在1秒后重试'%(who,e)
                self.sys_print(msg,show_force=1)
                time.sleep(1)
            

    def reconnect_callback(self,dict_data,callback=None):
        '''
        断线重连回调函数
        
        待开发
        '''
    
    def reconnect_success_callback(self,dict_data,callback=None):
        '''
        断线重连成功回调函数
        
        待开发
        
        Parameters
        ----------
        dict_data : TYPE
            DESCRIPTION.
        callback : TYPE, optional
            DESCRIPTION. The default is None.

        Returns
        -------
        None.

        '''
        pass
    
    
    def add_txg(self,channel_name,pwd=''):
        '''
        增加txg的订阅，同txg,用@符号连接多个信道
        如 'test@test1'
        '''
        if not self.run_on:
            msg = '识别到此前已经close过txl，重新运行self.run_on'
            self.sys_print(msg,show_force=True)
        if '@' in channel_name:
            for who in channel_name.split('@'):
                self.__connect_txg(who,pwd=pwd)
        else:
            who = channel_name
            self.__connect_txg(who,pwd=pwd)
    
    def __close_txg(self,who):
        txg = self.txg_dict[who]['con']
        self.txg_dict[who]['txg_running'] = False
        self.close_connection(txg,name=who)
    
    def cancel_txg(self,who):
        '''
        取消txg的订阅，同txg,用@符号连接多个信道
        '''        
        if who not in self.txg_dict:
            tem_dict = {'code':-1,
                        'msg':'当前%s频道未连接，取消失败'%(who),
                        'value':{},
                        }
        else:
            tem_dict = {'code':0,
                        'msg':'%s频道取消成功'%(who),
                        'value':{},
                        }            
            self.__close_txg(who)       
            
        return tem_dict
    
    def start_MQ(self,pub_port=5555):
        import zmq
        '''
        开启ZMQ模式，该模式是将ZMQ与LTtx进行功能上的整合，当前版本的断线重连机制完全依赖于ZMQ自身的
        断线重连机制

        Parameters
        ----------
        pub_port : int
            传入服务端的ZMQ发布端口，通常为5555.

        Returns
        -------
        None.

        '''
        if not self.__ZMQ:
            context = zmq.Context()
            
            # 创建发布者套接字并连接到代理
            socket = context.socket(zmq.PUB)
            socket.setsockopt(zmq.RCVHWM, 1000000)
            socket.setsockopt(zmq.SNDHWM, 1000000)
            socket.connect('tcp://%s:%s'%(self.ip,pub_port))
            socket.send_string('test dsfadsafdsafsda')
            self.__ZMQ = socket
            print(self.get_nowtime(),'zmq connect ok')
        else:
            # code = -1
            msg = 'start_MQ已经连接,请不要重复连接'
            msg = (self.get_nowtime(),msg)
            self.sys_print(msg)

        
    
    def start_MQ_broadcast(self,channel_list,sub_port=5556):
        '''
        开启ZMQ的订阅模式，同start_MQ

        Parameters
        ----------
        channel_list : string
            和start_txg()类似，传入要订阅的信道列表，用@进行分割.
        sub_port : int, optional
            传入服务端的ZMQ订阅端口，通常为5556

        Returns
        -------
        None.

        '''
        import zmq
        if not self.__ZMQ_broadcast:
            context = zmq.Context()

            # 创建订阅者套接字并连接到代理
            socket = context.socket(zmq.SUB)
            socket.setsockopt(zmq.RCVHWM, 1000000)
            socket.setsockopt(zmq.SNDHWM, 1000000)
            socket.connect("tcp://%s:%s"%(self.ip,sub_port))
            self.zmq_channel_list = channel_list.split('@')
            for channel in self.zmq_channel_list:
                if len(channel) > 0:
                    # 订阅特定主题
                    socket.setsockopt_string(zmq.SUBSCRIBE, channel)
            self.__ZMQ_broadcast = socket
            threading.Thread(target = self.main_recv_msg_from_zmq).start()
        else:
            # code = -1
            msg = 'MQ_broadcast已经连接,请不要重复连接'
            print(self.get_nowtime(),msg)
    
    def main_recv_msg_from_zmq(self):
        print(self.get_nowtime(),'开始从ZMQ中接收数据')
        while self.run_on:
            data = self.__ZMQ_broadcast.recv_string().split('|',1)
            if data[0] in self.zmq_channel_list:
                self.Q.put(data[1])
    
    def start_tx_hearbeat(self):
        while self.run_on:
            if self.__tx:
                self.push('heartbeat','1','heartbeat0')
                time.sleep(self.timeout)
            else:
                break

    def start_tx_hearbeat_plus(self):
        msg = ('start_tx_plus的heartbeat子线程启动')
        self.sys_print(msg)
        while self.run_on:
            if self.__tx_plus:
                self.push_plus('heartbeat','t','test22')
                time.sleep(2)
            else:
                break
            
    def __start_thread(self,target,args):
        thp1 = threading.Thread(target=target,args=args)
        # thp1.setDaemon(True)
        thp1.start()        
      
    
    def recv_msg_start_tx(self,client):
        
        data = client.recv(1024)
        dict_data = json.loads(data)
        code = dict_data['code']
        self.id_code = str(dict_data['id_code'])+'@'
        if 'server_version' in dict_data:
            if dict_data['server_version'] > 2:
                self.server2 = True
        if code == 0:
            return True
        else:
            return False
    
    def recv_msg_start_txg(self,client,timeout=None):
        if timeout:
            client.settimeout(timeout)
        data = client.recv(1024,)
        dict_data = json.loads(data)
        code = dict_data['code']
        if timeout:
            client.settimeout(None)
        if code == 0:
            return True
        else:
            return False
            
    def recv_data_from_tx(self,client):
        recv_bytes = client.recv(8,socket.MSG_WAITALL)
        bytes_len = struct.unpack("Q",recv_bytes)[0]
        recv_data = client.recv(bytes_len,socket.MSG_WAITALL).decode('utf-8',errors='replace')
        recv_data = json.loads(recv_data)
        return recv_data
    
    def get(self,key):
        '''
        获取云变量'key'对应的值，如果不存在则返回None
        '''
        if self.__tx == False:
            code = -1
            msg = '当前tx未连接,请先执行start_tx()'
            result = {'code':code,'msg':msg}
            return result
        else:
            send_data = {'func':'get','value':key}
            msg = self.json.dumps(send_data)
            self.send_data(self.__tx,msg)
            result = self.recv_data_from_tx(self.__tx)
            result = json.loads(result)
            if 'value' in result:
                result = result['value']
                self.heartbeat = 0
            return result
    
    def get_dict_value(self,var,key):
        '''
        获取云变量字典“key"中对应的key值，如果不存在则返回None
        '''
        if self.__tx == False:
            code = -1
            msg = '当前tx未连接,请先执行start_tx()'
            result = {'code':code,'msg':msg}
            return result
        else:
            send_data = {'func':'get_dict_value','value':(var,key)}
            msg = self.json.dumps(send_data)
            self.send_data(self.__tx,msg)
            result = self.recv_data_from_tx(self.__tx)
            result = json.loads(result)
            if 'value' in result:
                result = result['value']
                self.heartbeat = 0
            return result

    def get_list_value(self,key:str,index:int):
        '''
        获取云变量列表"key"中对应下标的为index的值，index传入整型，和list使用方法一致，如果不存在则返回为None。
        '''
        if self.__tx == False:
            code = -1
            msg = '当前tx未连接,请先执行start_tx()'
            result = {'code':code,'msg':msg}
            return result
        else:
            send_data = {'func':'get_list_value','value':(key,index)}
            msg = self.json.dumps(send_data)
            self.send_data(self.__tx,msg)
            result = self.recv_data_from_tx(self.__tx)
            result = json.loads(result)
            if 'value' in result:
                result = result['value']
                self.heartbeat = 0
            return result


    def get_df(self,key):
        import pandas as pd
        if self.__tx == False:
            code = -1
            msg = '当前tx未连接,请先执行start_tx()'
            result = {'code':code,'msg':msg}
            return result
        else:
            send_data = {'func':'get_dataframe','value':key}
            msg = self.json.dumps(send_data)
            self.send_data(self.__tx,msg)
            result = self.recv_data_from_tx(self.__tx)
            result = json.loads(result)
            if 'value' in result:
                result = result['value']
                result = pd.DataFrame(json.loads(result))
                self.heartbeat = 0
            return result


    def put(self,key,data):
        try:
            if self.__tx == False:
                code = -1
                msg = '当前tx未连接,请先执行start_tx()'
                result = {'code':code,'msg':msg}
                return result
            else:
                send_data = {'func':'put','value':(key,data)}
                msg = self.json.dumps(send_data)
                self.send_data(self.__tx,msg)
        except:
            msg = 'Error:和服务端失去连接，即将重连'
            self.sys_print(msg,show_force=1)
            self.__tx = False
            self.start_tx()
    
    def put_df(self,key,df):
        try:
            if self.__tx == False:
                code = -1
                msg = '当前tx未连接,请先执行start_tx()'
                result = {'code':code,'msg':msg}
                return result
            else:
                send_data = {'func':'put_dataframe','value':(key,json.dumps(df.to_dict(orient='records')))}
                msg = self.json.dumps(send_data)
                self.send_data(self.__tx,msg)
        except:
            msg = 'Error:put_df时和服务端失去连接，即将重连'
            self.sys_print(msg,show_force=1)
            self.__tx = False
            self.start_tx()
    


    def list_append(self,var,data):
        '''
        对云端变量类型为列表的var进行列表append操作，相当于本地列表的基础操作，无返回值，默认成功

        Parameters
        ----------
        key : TYPE
            DESCRIPTION.
        data : TYPE
            DESCRIPTION.

        Returns
        -------
        result : TYPE
            DESCRIPTION.

        '''
        try:
            if self.__tx == False:
                code = -1
                msg = '当前tx未连接,请先执行start_tx()'
                result = {'code':code,'msg':msg}
                return result
            else:
                send_data = {'func':'list_append','value':(var,data)}
                msg = self.json.dumps(send_data)
                self.send_data(self.__tx,msg)
        except:
            msg = 'Error:list_append和服务端失去连接，即将重连'
            self.sys_print(msg,show_force=1)
            self.__tx = False
            self.start_tx()
    
    def list_remove(self,var,data):
        '''
        对云端变量类型为列表的var进行列表remove操作，相当于本地列表的基础操作，无返回值，默认成功

        Parameters
        ----------
        key : TYPE
            DESCRIPTION.
        data : TYPE
            DESCRIPTION.

        Returns
        -------
        result : TYPE
            DESCRIPTION.

        '''
        try:
            if self.__tx == False:
                code = -1
                msg = '当前tx未连接,请先执行start_tx()'
                result = {'code':code,'msg':msg}
                return result
            else:
                send_data = {'func':'list_remove','value':(var,data)}
                msg = self.json.dumps(send_data)
                self.send_data(self.__tx,msg)
        except:
            msg = 'Error:list_remove时和服务端失去连接，即将重连'
            self.sys_print(msg,show_force=1)
            self.__tx = False
            self.start_tx()
    
    def list_pop(self,var,data):
        '''
        对云端变量类型为列表的var进行列表pop操作，相当于本地列表的基础操作，无返回值，默认成功

        Parameters
        ----------
        key : TYPE
            DESCRIPTION.
        data : TYPE
            DESCRIPTION.

        Returns
        -------
        result : TYPE
            DESCRIPTION.

        '''
        try:
            if self.__tx == False:
                code = -1
                msg = '当前tx未连接,请先执行start_tx()'
                result = {'code':code,'msg':msg}
                return result
            else:
                send_data = {'func':'list_pop','value':(var,data)}
                msg = self.json.dumps(send_data)
                self.send_data(self.__tx,msg)
        except:
            msg = 'Error:listpop和服务端失去连接，即将重连'
            self.sys_print(msg,show_force=1)
            self.__tx = False
            self.start_tx()
    
    def dict_change(self,var,key,value):
        '''
        对云端变量为var的字典进行字典操作，同基础的字典操作，无返回值，默认成功

        Parameters
        ----------
        var : TYPE
            DESCRIPTION.
        key : TYPE
            DESCRIPTION.
        value : TYPE
            DESCRIPTION.

        Returns
        -------
        result : TYPE
            DESCRIPTION.

        '''
        try:
            if self.__tx == False:
                code = -1
                msg = '当前tx未连接,请先执行start_tx()'
                result = {'code':code,'msg':msg}
                return result
            else:
                send_data = {'func':'dict_change','value':(var,key,value)}
                msg = self.json.dumps(send_data)
                self.send_data(self.__tx,msg)
        except:
            msg = 'Error:dict_change和服务端失去连接，即将重连'
            self.sys_print(msg,show_force=1)
            self.__tx = False
            self.start_tx()
    
    def push(self,key,data,who=None):
        try:
            if self.__tx == False:
                code = -1
                msg = '当前tx未连接,请先执行start_tx()'
                result = {'code':code,'msg':msg}
                return result
            else:
                send_data = {'func':'push','value':'%s|%s'%(key,data),'who':who}
                msg = self.json.dumps(send_data)
                self.send_data(self.__tx,msg)
                
        except Exception as e:
            raise ConnectionAbortedError('与服务器连接断开,push函数出错,请注意你传入的数据类型必须为字符串,请查看上方的报错内容>>>%s'%(e))
    
    def push_plus(self,key,data,who=''):
        '''
        超级push函数，会比push函数更快，效率更高，确保你传入的参数均为字符串，否则推送不成功

        Parameters
        ----------
        key : TYPE
            DESCRIPTION.
        data : TYPE
            DESCRIPTION.
        who : TYPE, optional
            DESCRIPTION. The default is None.

        Raises
        ------
        ConnectionAbortedError
            DESCRIPTION.

        Returns
        -------
        result : TYPE
            DESCRIPTION.

        '''
        try:
            if self.__tx_plus == False:
                code = -1
                msg = '当前tx_plus未连接,请先执行start_tx_plus()'
                result = {'code':code,'msg':msg}
                return result
            else:
                msg = key+'|'+data+':who:'+who
                self.send_data_plus(self.__tx_plus,msg)    
        except Exception as e:
            self.sys_print('push_plus出错了>>>>>%s'%(e))
            raise ConnectionAbortedError('与服务器连接断开,push_plus函数出错,请确保你传入的参数均为字符串，请查看上方的报错内容')
         
    def MQ_push(self,var,data,who):
        '''
        采用ZMQ模式进行push，速度更快，一百万次推送耗时在1.8秒左右，但对于数据安全性没有保障，适合大通量的行情推送，在测试时发现有数据不能
        完全到达的情况，请自行做好数据校验机制

        Parameters
        ----------
        var : TYPE
            DESCRIPTION.
        data : TYPE
            DESCRIPTION.
        who : TYPE
            DESCRIPTION.

        Returns
        -------
        None.

        '''
        if self.__ZMQ:
            self.__ZMQ.send_string('%s|%s|%s'%(who,var,data))
        else:
            return (-1,'请先执行start_MQ()')
    
    def recv_msg_put(self,client):
        data = client.recv(1024)
        dict_data = json.loads(data)
        return dict_data
    
    def send_data(self,client, msg):
        if not self.orjson_on:
            msg = msg.encode('utf-8')
        self.tx_que.put(msg)
    
    def send_data_plus(self,client, msg):
        self.tx_que_plus.put(msg)
    
    def __connect_d_push(self,):
        '''
        d_push连接        
        '''
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM) 
        client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8192*100)
        # 设置立即发送（关闭 Nagle 算法，降低延迟）
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        client.connect((self.ip,self.port))                    
        tem_dict = {'con_type':'put_mode','tocken':self.tocken,
                    'local_ip':self.local_ip,
                    'current_file':self.current_file,'current_dir':self.current_dir,                                
                    }
        self.sys_print(tem_dict)
        client.sendall(json.dumps(tem_dict).encode('utf-8'))
        if self.recv_msg_start_tx(client):
            self.__d_push_tx = client
        self.sys_print('d_push模式启动成功')
    def close_d_push(self):
        '''
        主动关闭d_push
        '''
        self.close_connection(self.__d_push_tx)   
        self.__d_push_tx = False
        self.sys_print('d_push模式主动关闭')
        
    def d_push(self,key,data,who):
        '''
        绕过多线程直接在当前线程进行消息推送，适合在QMT里直接调用,只适合在127.0.0.1里使用
        '''        
        if not self.__d_push_tx:
            # if self.ip != '127.0.0.1':
            #     raise OSError('d_push只能在127.0.0.1使用')
            self.__connect_d_push() 
        
        send_data = {'func':'push','value':'%s|%s'%(key,data),'who':who}
        msg = self.json.dumps(send_data)
        if not self.orjson_on:
            msg = msg.encode('utf-8')
        data_len = len(msg)
        struct_bytes = struct.pack('Q', data_len)
        try:
            self.__d_push_tx.sendall(struct_bytes)
            self.__d_push_tx.sendall(msg)
        except Exception as e:
            try:
                self.close_d_push()
            except:
                msg = 'd_push关闭异常，请留意'
                self.__d_push_tx = False
            self.__connect_d_push()
            self.sys_print('d_push异常>>>%s'%(str(e)))

    def main_tx_que(self):
        while self.run_on:
            try:
                msg = self.tx_que.get()                
                data_len = len(msg)
                struct_bytes = struct.pack('Q', data_len)
                self.__tx.sendall(struct_bytes)
                self.__tx.sendall(msg)
            except Exception as e:
                if self.run_on:
                    msg = 'start_tx在发送数据时出错了,开始重连>>>>%s'%(e)
                    self.sys_print(msg,show_force=True)
                    self.__tx = False
                    self.close_tx()
                    self.start_tx()      
                    time.sleep(2)
                break
            
    def main_tx_que_plus(self):
        while self.run_on:
            try:
                old_msg = self.tx_que_plus.get()
                msg=old_msg.encode('utf-8')
                data_len = len(msg)
                struct_bytes = struct.pack('Q', data_len)
                self.__tx_plus.sendall(struct_bytes)
                self.__tx_plus.sendall(msg)
            except:
                self.__tx_plus = False
                self.start_plus()
                self.tx_que_plus.put(old_msg)
                break
    
    def recv_msg_broadcast(self,who,client,pwd):
        while self.run_on:
            try:                
                recv_data = self.recv_data_from_tx(client)
                if '|' in recv_data:
                    self.Q.put(recv_data)
                else:                    
                    self.__txg_heartbeat_time = time.time()
            except Exception as e:
                try:
                    self.close_connection(client,name='txg')         
                except:
                    pass
                break
        #         try:
        #             if self.txg_dict[who]['txg_running'] == True:
        #                 self.txg_dict[who]['txg_running'] = False
        #                 data = {'txg断线时间':self.get_nowtime(),'断线原因':str(e)}
        #                 self.sys_print(data,show_force=True)
        #                 threading.Thread(target = self.loss_connect_callback,args=(data,)).start()                         
        #                 self.close_connection(client,name='txg')                    
        #                 msg = 'txg因报错主动关闭退出'
        #                 self.sys_print(msg,show_force=True)
        #                 break
        #             else:
        #                 print('我断线了哦')
        #                 break
        #         except Exception as e:
        #             data = {'txg断线时间':self.get_nowtime(),'断线原因2':str(e),'断线逻辑':'处理断线时出错'}
        #             self.sys_print(data,show_force = True)                    
        #             break
        # time.sleep(2)#休息5秒后判断当前是不是直接的断线了，然后再重连
        # if self.__tx and self.txg_running:
        #     self.sys_print("内部错误导致txg断开，即将重连")
        #     self.__connect_txg(who=who,pwd=pwd)
        # self.sys_print('我已全部退出')
    def main_broadcast_heartbeat(self,client,who,pwd):
        while self.run_on:
            try:
                msg = b'1'
                client.sendall(msg)                
            except Exception as e:
                msg = 'txg心跳失败，开始重连>>>>%s'%(e)
                self.txg_dict[who]['txg_running'] = False
                self.sys_print(msg)
                break
            time.sleep(1)
        print('退出心跳------')
        if who in self.txg_dict and not self.txg_dict[who]['txg_running']:
            self.__connect_txg(who,pwd=pwd)
        print('我全退出了')
    
    
    def create_channel(self,num=30):
        '''
        创建一个随机信道，默认长度为30位字符串

        Parameters
        ----------
        num : int
            要创建的随机信道长度，默认为30位

        Returns
        -------
        None.

        '''        
        s='abcdefghijklmnopqrstuvwxz12345678901'
        str1 = ''
        for i in range(num):
            str1 = str1 + s[random.randint(0,35)]
        return str1 
    
    def close_connection(self,client,name='tx'):
        try:
            # 强制停止读写操作，确保 recv 不再阻塞
            client.shutdown(socket.SHUT_RDWR)
        except socket.error as e:
            self.sys_print('关闭socket出错了>>>>,类型为:%s'%(name),e)
        finally:
            client.close()

    def close_tx(self):
        self.tx_running = False
        if self.__tx == False:
            code = -1
            msg = '当前tx未连接'
        else:
            if self.txg_running:
                self.close_txg()
            if type(self.__tx) != bool:
                self.close_connection(self.__tx)            
            self.__tx = False
            self.tx_que.put('')
            code = 0
            msg = 'tx关闭成功,txg也关闭成功'   
        result = {'code':code,'msg':msg}
        return result
    
    def close_tx_plus(self,):
        '''
        关闭push_plus功能

        Returns
        -------
        None.

        '''
        if self.__tx_plus == False:
            code = -1
            msg = '当前tx_plus功能未开启'
            result = {'code':code,'msg':msg}
            self.sys_print(result)
            return result
        else:
            self.close_connection(self.__tx_plus)
            self.__tx_plus = False
            
            code = 0
            msg = 'tx_plus关闭成功'
            result = {'code':code,'msg':msg}
            self.sys_print(result)
            return result
    
    def close(self,):
        '''
        关闭所有的连接对象，该函数会直接关闭
        '''
        if self.run_on:
            self.run_on = False
            self.close_tx()
            self.close_txg()
            self.close_tx_plus()
            msg = '手动关闭所有连接,将在1秒后退出'
            self.sys_print(msg,show_force=True)            
            time.sleep(1)
    
        
    
    def close_txg(self):
        self.txg_running = False
        self.sys_print(self.tx_running,self.__tx)
        for who in list(self.txg_dict.keys()):
            self.__close_txg(who)   
        if not self.tx_running:
            self.close_tx()
            self.sys_print('关闭跟随启动的tx')
                   
        self.txg_dict = {}
        result = {'code':0,'msg':'所有txg关闭成功','value':{}}
        return result
    
    def get_nowdate(self,):
        '''
        返回当前的日期，格式为2024-04-04
        '''
        return time.strftime("%Y-%m-%d")

    def get_nowmin(self,):
        '''
        返回当前的时间，格式为19:00:00
        ''' 
        return time.strftime('%H:%M:%S')

    def get_nowtime(self,):
        '''
        返回当前时间，格式为2023-11-15 20:02:01

        Returns
        -------
        TYPE
            DESCRIPTION.

        '''
        return time.strftime('%Y-%m-%d %H:%M:%S',time.localtime())
    
    def get_timestamp(self):
        '''
        返回当前数字时间戳

        Returns
        -------
        None.

        '''
        return time.time()
    
    def DatestrtingToInt(self,time_str):
        '''
        把2023-10-15 20:02:01转为1697371321

        Parameters
        ----------
        time_str : string
            2023-10-15 20:02:01

        Returns
        -------
        timestamp : int
            返回整形时间戳1697371321.

        '''
        dt = datetime.datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
        timestamp = int(dt.timestamp())
        return timestamp
    def IntTimeToString(self,ct):
        '''
        把
        conv_time(1697371321) --> '2023-10-15 20:02:01'
        '''
        local_time = time.localtime(ct)
        data_head = time.strftime('%Y-%m-%d %H:%M:%S', local_time)
        return data_head

    def calc_datetime_day(self,str1,str2):
        '''
        计算2023-10-15 20：24：55和2023-10-14 20：24：55之间的天数

        Parameters
        ----------
        str1 : TYPE
            DESCRIPTION.
        str2 : TYPE
            DESCRIPTION.

        Returns
        -------
        TYPE
            DESCRIPTION.

        '''
        return (datetime.datetime.strptime(str1, '%Y-%m-%d %H:%M:%S') - datetime.datetime.strptime(str2, '%Y-%m-%d %H:%M:%S')).days
    
    
    
    def loss_connect_callback(self,data):
        if self.loss_callback:
            self.loss_callback(data)
    
    def regest_loss_connect_callback(self,func):
        '''
        该功能暂时不可用，待开发
        注册失去连接时的回调函数,callback会传入一个字典参数,
        '''
        # self.loss_callback = func
        # msg = '连接断开回调函数注册成功，将在断网时回调'
        # self.sys_print(msg)
        pass
        
    
    def calc_datetime_seconds(self,str1,str2):
        '''计算秒差'''
        return (datetime.datetime.strptime(str1, '%Y-%m-%d %H:%M:%S') - datetime.datetime.strptime(str2, '%Y-%m-%d %H:%M:%S')).seconds
    
    def calc_datetime_minutes(self,str1,str2):
        '''计算分钟差'''
        return (datetime.datetime.strptime(str1, '%Y-%m-%d %H:%M:%S') - datetime.datetime.strptime(str2, '%Y-%m-%d %H:%M:%S')).seconds // 60
    
    def calc_zdf(N1,N2):
        '''
        计算两个值的涨跌百分比，通常用在计算收益率中
        '''
        return (N1-N2)/N2 * 100

    def get_day_before(self,datestr,N):
        '''向前取N天,传入2023-10-15的格式'''
        date = datetime.datetime.strptime(datestr, '%Y-%m-%d')
        date_before = date - datetime.timedelta(days=N)
        return str(date_before.date())

    def get_day_next(self,datestr,N):
        '''
        向前取N天，传入2023-10-14的格式
        '''
        date = datetime.datetime.strptime(datestr, '%Y-%m-%d')
        date_before = date + datetime.timedelta(days=N)
        return str(date_before.date())
    
    def get_day_cha(self,datestr,N):
        '''
        返回N天后的日期，注意N的正负号，传入"2024-04-16 15:00:00"或者"15:00:00"
        返回值为字符串,如果N为3，返回"2024-04-19 15:00:00"
        '''
        if ' ' in datestr:
            date = datetime.datetime.strptime(datestr, '%Y-%m-%d %H:%M:%S')
        else:
            date = datetime.datetime.strptime(datestr, '%H:%M:%S')
        if N > 0:
            date_before = date + datetime.timedelta(days=N)
        else:
            date_before = date - datetime.timedelta(days=-N)
        if ' ' in datestr:
            result = str(date_before)
        else:
            result = str(date_before).split(' ')[1]
        return result


    def get_min_cha(self,datestr,N):
        '''
        返回分钟差后的日期，注意N的正负号，传入"2024-04-16 15:00:00"或者"15:00:00"
        返回值为字符串
        '''
        if ' ' in datestr:
            date = datetime.datetime.strptime(datestr, '%Y-%m-%d %H:%M:%S')
        else:
            date = datetime.datetime.strptime(datestr, '%H:%M:%S')
        if N > 0:
            date_before = date + datetime.timedelta(minutes=N)
        else:
            date_before = date - datetime.timedelta(minutes=-N)
        if ' ' in datestr:
            result = str(date_before)
        else:
            result = str(date_before).split(' ')[1]
        return result
    
    def get_second_cha(self,datestr,N):
        '''
        返回秒差后的日期，注意N的正负号，传入"2024-04-16 15:00:00"或者"15:00:00"
        返回值为字符串
        '''
        if ' ' in datestr:
            date = datetime.datetime.strptime(datestr, '%Y-%m-%d %H:%M:%S')
        else:
            date = datetime.datetime.strptime(datestr, '%H:%M:%S')
        if N > 0:
            date_before = date + datetime.timedelta(seconds=N)
        else:
            date_before = date - datetime.timedelta(seconds=-N)
        if ' ' in datestr:
            result = str(date_before)
        else:
            result = str(date_before).split(' ')[1]
        return result
    
    def judge_is_TradeDay(self,datestr=None):
        '''
        判断datestr是不是A股交易日,需要先安装pandas_market_calendars库的支持
        如果没有传入日期，则返回判断当天是不是交易日

        Parameters
        ----------
        datestring : TYPE
            DESCRIPTION.

        Returns
        bool
        -------
        如果时交易日则返回为True,否则为False.

        '''
        if not datestr:
            datestr = time.strftime("%Y-%m-%d")
        if datestr in self.dict_TradeDay:
            return self.dict_TradeDay[datestr]
        
        import pandas_market_calendars as mcal
        sse = mcal.get_calendar('SSE')#上海证券交易所日历
        td_df = sse.schedule(start_date=datestr, end_date=datestr)
        if len(td_df) > 0:
            result = True
        else:
            result = False
        self.dict_TradeDay[datestr] = result
        return result

    def get_last_TradeDay(self,):
        '''
        返回中国A股市场最近的一个交易日        
        '''
        import pandas_market_calendars as mcal
        sse = mcal.get_calendar('SSE')#上海证券交易所日历
        now_date = time.strftime("%Y-%m-%d")
        last_date = self.get_day_before(now_date,30)
        td_df = sse.schedule(start_date=last_date, end_date=now_date)        
        result = str(td_df.index[-1]).split(' ')[0]
        return result
    
    def get_TradeDay_List(self,N1,N2):
        '''
        获取N1到N2之间的中国交易日,传入字符串时间
        N1: 2025-01-01
        N2: 2025-01-12
        '''
        import pandas_market_calendars as mcal        
        sse = mcal.get_calendar('SSE')#上海证券交易所日历        
        td_df = sse.schedule(start_date=N1, end_date=N2)   
        l1 = []
        for i in list(td_df.index):
            l1.append(str(i).split(' ')[0])
        
        return l1
    
    def cal_trade_day_cha(self,str1:str,str2:str)->int:
        '''
        获取两个日期之间的交易日天数，传入格式：
        str1:2025-12-30
        str2:2026-01-06
        返回整数
        '''        
        if str1 == str2:
            return 0
        if self.td_df.empty:
            import pandas_market_calendars as mcal        
            self.sse = mcal.get_calendar('SSE')#上海证券交易所日历        
            self.td_df = self.sse.schedule(start_date=str1, end_date=str2)        
        if str1 < str(self.td_df.index[0]) or str2 > str(self.td_df.index[-1]):
            self.td_df = self.sse.schedule(start_date=str1, end_date=str2)  
        tem_df = pd.DataFrame()
        tem_df['交易日'] = self.td_df.index
        tem_df['交易日'].apply(lambda x:str(x))
        tem_td_df = tem_df[tem_df['交易日'] >= str1]
        tem_td_df = tem_td_df[tem_td_df['交易日'] <= str2]
        result = len(tem_td_df)
        return result
        
    def get_pre_TradeDay(self,N=1):
        '''
        返回A股市场上N个交易日，默认为1，即返回昨日，0表示返回最近一个交易日
        '''
        import pandas_market_calendars as mcal
        now_date = self.get_nowdate()
        if now_date != self.pre_TradeDay['now_date']:            
            self.pre_TradeDay = {'now_date':now_date} 
            sse = mcal.get_calendar('SSE')#上海证券交易所日历
            now_date = time.strftime("%Y-%m-%d")
            last_date = self.get_day_before(now_date,N+30)
            td_df = sse.schedule(start_date=last_date, end_date=now_date)        
            result = str(td_df.index[-(N+1)]).split(' ')[0]
            self.pre_TradeDay[N] = result
        if N not in self.pre_TradeDay:
            self.pre_TradeDay = {'now_date':now_date} 
            sse = mcal.get_calendar('SSE')#上海证券交易所日历
            now_date = time.strftime("%Y-%m-%d")
            last_date = self.get_day_before(now_date,N+30)
            td_df = sse.schedule(start_date=last_date, end_date=now_date)        
            result = str(td_df.index[-(N+1)]).split(' ')[0]
            self.pre_TradeDay[N] = result
        result = self.pre_TradeDay.get(N)
        return result
        
    def get_local_ip(self,):
        '''返回局域网IPV4地址'''
        import socket
        try:
            # 创建一个socket对象
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # 不需要真的连接，所以使用一个不存在的地址
            s.connect(("10.255.255.255", 1))
            IP = s.getsockname()[0]
        except Exception:
            IP = "127.0.0.1"  # 如果出现异常，则返回回环地址
        finally:
            s.close()  # 关闭socket
        return IP
    
    def get_public_ip(self,):
        '''
        返回公网IPV4地址
        '''
        response = requests.get('https://httpbin.org/ip')
        ip = response.json().get('origin')
        return ip

    def judge_Time_between(self,str1,str2):
        '''
        判断当前时间是不是介于str1和str2之间
        str1格式: '15:00:05'
        str2格式: '16:00:00'
        
        '''
        return str1 < time.strftime('%H:%M:%S') < str2
    

    def save_json(self,file_name,obj):
        with open(file_name,'w',encoding='utf-8') as f:
            json.dump(obj,f,ensure_ascii=False,indent=2)
            

    def load_json(self,file_name):
        with open(file_name,'r',encoding='utf-8') as f :
            data = json.load(f)
        return data
    
    def save_json_fix(self,file_name,dict_obj):
        '''
        保存json，会自动将不符合的json数据转为正常的，如numpy.float64转为正常的float64，
        传入的对象为字典

        待开发
        '''
    
    def mkdir(self,file_name):
        '''
        创建一个目录，如果已经存在则会跳过
        '''
        try:
            os.mkdir(file_name)
        except:
            pass
        
    @staticmethod
    def proxy(ip, port, user='', passwd='', proxy_type='http', ssh_remote_host='', ssh_remote_port=0, ssh_bind_port=10800):
        '''
        实现在程序内部通过 http、socks5 或 ssh 建立代理。
    
        - proxy_type: 可选 'http', 'socks5', 'ssh'
        - ssh_remote_host/ssh_remote_port: 仅在 proxy_type 为 ssh 时使用，表示远程跳板机地址和端口
        - ssh_bind_port: 本地映射端口（默认 10800）
    
        使用示例：
        @tx1.proxy(ip='127.0.0.1', port=1080, proxy_type='socks5')
        def get_data():
            pass
    
        @tx1.proxy(ip='ssh_server_ip', port=22, user='ssh_user', passwd='ssh_pass', proxy_type='ssh',
                   ssh_remote_host='8.8.8.8', ssh_remote_port=80)
        def get_data():
            pass
        '''
        from functools import wraps
        import socket
        import socks
    
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                if proxy_type.lower() == 'ssh':
                    from sshtunnel import SSHTunnelForwarder
    
                    server = SSHTunnelForwarder(
                        (ip, port),  # SSH 跳板机的 IP 和端口
                        ssh_username=user,
                        ssh_password=passwd,
                        remote_bind_address=(ssh_remote_host, ssh_remote_port),
                        local_bind_address=('127.0.0.1', ssh_bind_port)
                    )
    
                    server.start()
                    print(f"[SSH代理] 本地代理端口: {server.local_bind_port}")
    
                    try:
                        # 对于 SSH 场景，将请求转发到本地代理端口
                        proxies = {
                            'http': f'http://127.0.0.1:{server.local_bind_port}',
                            'https': f'http://127.0.0.1:{server.local_bind_port}',
                        }
                        kwargs['proxies'] = proxies
                        return func(*args, **kwargs)
                    finally:
                        server.stop()
                        print("[SSH代理] 隧道已关闭")
    
                elif proxy_type.lower() == 'socks5':
                    socks.set_default_proxy(socks.SOCKS5, ip, port, username=user, password=passwd)
                    socket.socket = socks.socksocket
                    return func(*args, **kwargs)
    
                else:  # 默认 HTTP/HTTPS
                    if user and passwd:
                        proxy_url = f"{proxy_type}://{user}:{passwd}@{ip}:{port}"
                    else:
                        proxy_url = f"{proxy_type}://{ip}:{port}"
                    proxies = {
                        'http': proxy_url,
                        'https': proxy_url,
                    }
                    kwargs['proxies'] = proxies
                    return func(*args, **kwargs)
    
            return wrapper
        return decorator




if __name__=='__main__':   
    import requests
    ip = 'dm432.zl45lkjrlewklrewnet.top'#把这里替换成你服务器实际的信息即可,可以是域名，也可以是IP地址
    ip = '192.168.1.70'#把这里替换成你服务器实际的信息即可
    # ip = '127.0.0.1'    
    ip = 'tx.txquant.cn'   
    port = 2049
   
    tocken = 'LTtx'#替换成服务端的token，默认为LTtx
    def call_back(data):

        print(data)
    
    tx1=txl(ip,port,tocken,loss_callback=call_back)
    # tx1.start_tx()
    tx1.start_txg('litao@test20@GY_HQ_test')    
    
    dict_count = {'count':0}#用来计数统计的，不用理会
    # print('okkkk')
    def show():
        '''
        打印收到的数据，实际处理时不需要用这个，只是为了测试用
        '''
        while True:
            data = tx1.Q.get().split('|')
            print(data)
            try:
                dict_count['count'] = int(data[0].split('_')[-1])
            except:
                pass
            try:
                yanchi = round((time.time() - float(data[1])) * 1000,9)
                print('数据延迟>>>%s ms'%(yanchi))
            except:
                pass
    threading.Thread(target = show).start()
   

    #延迟测试    
    send_len = 10
    send_len = 1 * 10**6
    tx1.push('afds_%s'%(2),time.time(),'litao')
    t1 = time.time()

    for i in range(send_len):
        tx1.push('afds_%s'%(i),time.time(),'litao')
        # time.sleep(0.1)
    while 1:
        if tx1.tx_que.empty():
            break    
        time.sleep(0.1)
    send_use_time = time.time() - t1
    while 1:
        if dict_count['count'] == send_len - 1:
            break
        time.sleep(0.1)
    recv_use_time = time.time() - t1
    print('发送%s万条time.time()数据用时>>>>>>>>>%s秒'%(send_len/10000,send_use_time))
    print('接收%s万条time.time()数据用时>>>>>>>>>%s秒'%(send_len/10000,recv_use_time))
    # while 1:
    #     time.sleep(1)




