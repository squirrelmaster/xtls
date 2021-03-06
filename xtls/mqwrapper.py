#!/usr/bin/env python
# -*- coding:utf-8 -*-
import re
import sys
from pprint import pprint
from functools import wraps
# try:
#     from cPickle import dumps, loads
# except ImportError:
#     from pickle import dumps, loads

from json import loads, dumps

from errors import ConsumerFatalError, ProducerFatalError
reload(sys)
sys.setdefaultencoding("utf-8")

URI_BASE = 'failover:({host})?initialReconnectDelay=1000,randomize=false,startupMaxReconnectAttempts={start},maxReconnectDelay=10000,maxReconnectAttempts={reconn}'

_deal_uri = lambda uri: uri if re.match(ur'tcp://(.+?):(\d+)', uri) else 'tcp://{host}:61613'.format(host=uri)


def _build_uri(uri, startup_times=-1, reconnect_times=-1):
    return URI_BASE.format(host=_deal_uri(uri), start=startup_times, reconn=reconnect_times)


def _deal_logger(logger):
    if logger:
        return logger.info, logger.exception
    return pprint, pprint


def _conn(cfg_uri, queue, _info):
    from stompest.config import StompConfig
    from stompest.sync import Stomp

    _info('Init Stomp obj: [%s-%s]' % (cfg_uri, queue))
    client = Stomp(StompConfig(cfg_uri))
    _info('connecting... %s' % cfg_uri)
    client.connect()
    _info('connected %s' % cfg_uri)
    return client


def consumer(cfg_uri, queue, logger=None, fetchsize=1):
    """
    分布式爬虫的爬虫端（具体爬虫部分）
    被包装的函数必须满足如下要求：
       1. 有且仅有一个参数
       2. 对于每个任务，返回两个参数： code, message

    :param cfg_uri: 读取任务的路径
    :param queue: Queue的名字
    :param logger: 日志记录工具
    :param fetchsize: 每次取出消息数量
    """
    from stompest.protocol import StompSpec

    _info, _exception = _deal_logger(logger)
    cfg_uri = _build_uri(cfg_uri)

    def decorator(function):

        def _build_conn():
            client = _conn(cfg_uri, queue, _info)
            client.subscribe(queue, {
                StompSpec.ACK_HEADER: StompSpec.ACK_CLIENT_INDIVIDUAL,
                'activemq.prefetchSize': fetchsize
            })
            return client

        @wraps(function)
        def wapper():
            client = _build_conn()
            while True:
                try:
                    frame = client.receiveFrame()
                    _info('got new frame %s' % frame)
                    param = loads(frame.body)
                    code, msg = function(param)
                    _info('result of task [%s]: [%s]-[%s]' % (frame.body, code, msg))
                except (KeyboardInterrupt, AssertionError, ConsumerFatalError), e:
                    _exception(e)
                    break
                except Exception, e:
                    _exception(e)
                finally:
                    try:
                        client.ack(frame)
                    except Exception, e:
                        _exception(e)
                        client.close()
                        client = _build_conn()
            client.disconnect()
            _info('disconnected %s' % cfg_uri)
        return wapper
    return decorator


def producer(cfg_uri, queue, logger=None):
    """
    分布式爬虫的任务端（将任务加入Queue）

    注意：
        被包装的函数需要返回一个可迭代的对象

    :param cfg_uri: 读取任务的路径
    :param queue: Queue的名字
    :param logger: 日志记录工具
    """
    _info, _exception = _deal_logger(logger)
    cfg_uri = _deal_uri(cfg_uri)

    def decorator(function):
        @wraps(function)
        def wapper(*args, **kwargs):
            client = _conn(cfg_uri, queue, _info)
            for item in function(*args, **kwargs):
                try:
                    if not isinstance(item, dict):
                        item = {'data': item}
                    data = dumps(item, ensure_ascii=False)
                    client.send(queue, data, headers={'persistent': 'true'})
                    _info('Producer insert %s - %s' % (queue, item))
                except ProducerFatalError, e:
                    _exception(e)
                    break
                except Exception, e:
                    _exception(e)
            client.disconnect()
            _info('disconnected %s' % cfg_uri)
        return wapper
    return decorator


""" ################ USEAGE #######################
@producer('192.168.31.116', queue='/queue/test')
def _produce(size):
    for x in xrange(size):
        yield {'key': x}


@consumer('192.168.31.116', queue='/queue/test)
def _task(key):
    print key
    print '-' * 120
    return 0, 'msg of task'
"""

if __name__ == '__main__':
    _task()
    # _produce(10)
    # _produ