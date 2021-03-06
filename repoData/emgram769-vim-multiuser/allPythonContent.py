__FILENAME__ = vim_multiuser_tests
import unittest
import vim_multiuser as sut


@unittest.skip("Don't forget to test!")
class VimMultiuserTests(unittest.TestCase):

    def test_example_fail(self):
        result = sut.vim_multiuser_example()
        self.assertEqual("Happy Hacking", result)

########NEW FILE########
__FILENAME__ = vim_multiuser
import vim
import threading
from vim_multiuser_server import *
import random

"""
Globals
"""
MUConnection = None
old_buffer = []
old_tick = 0
cursors = {}
user_name = ""

"""
Set up functions (called directly from vim_multiuser.vim)
"""
def start_multiuser_server(port, name=""):
    global user_name
    if name != "":
        user_name = name
    else:
        user_name = "User"+str(random.randint(0,100000))
    global MUConnection
    MUConnection = MUServer('0.0.0.0', port, parse_data)
    comm = threading.Thread(target=asyncore.loop,kwargs={'map':session_list})
    comm.daemon = True
    comm.start()

def start_multiuser_client(host, port, name=""):
    global user_name
    if name != "":
        user_name = name
    else:
        user_name = "User"+str(random.randint(0,100000))
    global MUConnection
    MUConnection = MUClient(host, port, parse_data)
    comm = threading.Thread(target=asyncore.loop)
    comm.daemon = True
    comm.start()

"""
parse_data:

    This function is responsible for all parsing of data
    and loading of data into the vim buffer.

TODO:

    - Cursor handling

"""
def parse_data(data):
    try:
        recv_data = json.loads(data)

        if ('user_name' in recv_data and 'cursor_row' in recv_data
            and 'cursor_col' in recv_data):
            if recv_data[u'user_name'] not in cursors:
                user_id = len(cursors)+6
            else:
                user_id = cursors[recv_data[u'user_name']][2]
                vim.command(':call matchdelete('+str(user_id)+')')

            # Update the cursor dict with row, col, color
            cursors[recv_data[u'user_name']] = (
                recv_data[u'cursor_row'],
                recv_data[u'cursor_col'],
                user_id)

            # Update collaborator cursor visually
            vim.command(':call matchadd(\'CursorHighlight\',\'\%'+
                str(recv_data[u'cursor_col'])+
                'v.\%'+str(recv_data[u'cursor_row'])+
                'l\', 1, '+str(user_id)+')')

        # Line update --> simply swap out line with new one
        elif ('line_num' in recv_data and 'line' in recv_data):
            line_num = recv_data[u'line_num']
            line = recv_data[u'line'].encode('ascii', 'ignore')
            vim.current.buffer[line_num] = line

        # Full body update --> swap entire buffer
        elif ('body' in recv_data):
            vim_list = recv_data[u'body']
            vim.current.buffer[:] = (
                    [vim_list[i].encode('ascii', 'ignore') 
                        for i in xrange(len(vim_list))])

        # Insert new line --> insert line and shift everything else down
        # TODO: move cursor with it
        elif ('insert' in recv_data):
            line_num = recv_data[u'insert']
            line = recv_data[u'line'].encode('ascii', 'ignore')

            vim.current.buffer[line_num+1:] = vim.current.buffer[line_num:]
            if line_num >= len(vim.current.buffer):
                vim.current.buffer[line_num:] = [line]
            else:
                vim.current.buffer[line_num] = line

        # Delete line --> remove line
        # TODO: move cursor appropriately
        elif ('delete' in recv_data):
            line_num = recv_data[u'delete']
            del vim.current.buffer[line_num]
        
        # Buffer has been updated, save that fact
        old_buffer = list(vim.current.buffer)

        vim.command(":redraw")

    # Bad data
    except ValueError, e:
        pass


"""
multiuser_client_send:

    This function determines what has changed in the file
    and then sends that data.

    Called on all cursor movement.
    
TODO:
    - Call on all key inputs
    - Better determine what has changed
    
"""
def multiuser_client_send():
    global old_buffer
    global MUConnection
    global old_tick
    
    if MUConnection == None:
        return
    
    # Send cursor data
    update_cursor(*vim.current.window.cursor)
            
    # Check if there are changes
    new_tick = int(vim.eval("b:changedtick"))
    if old_tick != new_tick:
        old_tick = new_tick
    else:
        return
    
    # Get the current buffer
    current_buffer = list(vim.current.buffer)
    
    # Bools for quick checks
    c_b_len = len(current_buffer)
    o_b_len = len(old_buffer)
    equal_length = c_b_len == o_b_len
    deleting = c_b_len + 1 == o_b_len
    inserting = c_b_len == o_b_len + 1
    large_insert = c_b_len > o_b_len and not inserting
    large_delete = c_b_len < o_b_len and not deleting
    
    # Get the cursor position
    row,col = vim.current.window.cursor

    # Changes, but no insert or delete
    if (equal_length
      and current_buffer[row-1] != old_buffer[row-1]
      and row-1 < len(old_buffer)):
        line = current_buffer[row-1]
        line_num = row-1
        update_line(line, line_num)
        
        
    # Maybe insert, maybe delete
    elif not equal_length and not old_buffer == []:
        
        # we are inserting one line
        if (inserting):
            line = current_buffer[row-1]
            line_num = row-1
            prev_line = current_buffer[row-2]
            insert_line(line, prev_line, line_num)
            
        # we are deleting one line
        elif (deleting):
            prev_line = current_buffer[row-1]
            delete_line(prev_line, row)
        
        # we are inserting multiple lines
        elif (large_insert):
            MUConnection.send_message({
            'body':list(vim.current.buffer)
            })
            
        # we are deleting multiple lines
        elif (large_delete):
            MUConnection.send_message({
            'body':list(vim.current.buffer)
            })

    # Store the buffer
    old_buffer = current_buffer

"""
Utility functions for creating messages to send
"""

def insert_line(line, prev_line, line_num):
    to_send = dict()
    to_send['line'] = line
    to_send['insert'] = line_num
    MUConnection.send_message(to_send)
    if (line_num > 0):
        update_line(prev_line, line_num-1)

def delete_line(prev_line, line_num):
    to_send = dict()
    to_send['delete'] = line_num
    MUConnection.send_message(to_send)
    if (line_num > 0):
        update_line(prev_line, line_num-1)
    
def update_line(line, line_num):
    to_send = dict()
    to_send['line'] = line
    to_send['line_num'] = line_num
    MUConnection.send_message(to_send)
    
def update_cursor(row, col):
    global user_name
    to_send = dict()
    to_send['user_name'] = user_name
    to_send['cursor_row'] = row
    to_send['cursor_col'] = col
    MUConnection.send_message(to_send)

########NEW FILE########
__FILENAME__ = vim_multiuser_server
import socket
import asyncore, asynchat
import sys, time
import vim
import json

"""
Globals
"""
session_list = {}

"""
Main Server Session Handler Class

"""
class MUSessionHandler(asynchat.async_chat):
    def __init__(self, sock, callback):
        asynchat.async_chat.__init__(self, sock=sock, map=session_list)
        
        self.set_terminator('\r\n')
        self.buffer = []
        self.callback = callback

    def collect_incoming_data(self, data):
        self.buffer.append(data)

    def found_terminator(self):
        data = ''.join(self.buffer)
        self.callback(data)
        for handler in session_list.itervalues():
            if hasattr(handler, 'push') and handler != self:
                handler.push(data + '\r\n')
        self.buffer = []

    def handle_close(self):
        asynchat.async_chat.handle_close(self)

"""
Main Server Class

"""
class MUServer(asyncore.dispatcher):
    def __init__(self, host, port, callback):
        asyncore.dispatcher.__init__(self, map=session_list)
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.bind((host, port))
        self.listen(5)
        self.callback = callback

    def handle_accept(self):
        pair = self.accept()
        if pair is not None:
            sock, addr = pair
            handler = MUSessionHandler(sock, self.callback)
            
            # Initialize remote client with current buffer
            handler.push(json.dumps({
                'body':list(vim.current.buffer)
                })+'\r\n')

    def broadcast(self, msg):
        for handler in session_list.itervalues():
            if hasattr(handler, 'push'):
                handler.push(msg)

    def send_message(self, msg):
        self.broadcast(json.dumps(msg)+'\r\n')
        
"""
Main Client Class

"""
class MUClient(asynchat.async_chat):

    def __init__(self, host, port, callback):
        asynchat.async_chat.__init__(self)
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connect((host, port))

        self.set_terminator('\r\n')
        self.buffer = []
        self.callback = callback

    def collect_incoming_data(self, data):
        self.buffer.append(data)

    def found_terminator(self):
        data = ''.join(self.buffer)
        self.callback(data)
        self.buffer = []

    def send_message(self, msg):
        self.push(json.dumps(msg)+'\r\n')

    def handle_close(self):
        asynchat.async_chat.handle_close(self)

########NEW FILE########
