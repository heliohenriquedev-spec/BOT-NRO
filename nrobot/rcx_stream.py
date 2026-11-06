"""Small seqlocked local mmap: terrain packets bypass JSON/UI refresh delays."""
import json
import mmap
import struct
import time
from pathlib import Path

SIZE = 4*1024*1024
MAGIC = b'RCX2'


class Publisher:
    def __init__(self, path):
        self.file = Path(path).open('w+b')
        self.file.truncate(SIZE)
        self.memory = mmap.mmap(self.file.fileno(), SIZE, access=mmap.ACCESS_WRITE)
        self.sequence = 0

    def publish(self, value):
        data = json.dumps(value, separators=(',', ':')).encode('utf-8')
        if len(data)>SIZE-16:raise ValueError('Limite do canal RCX excedido')
        self.sequence += 2
        self.memory[:12] = struct.pack('<4sII',MAGIC,self.sequence-1,len(data))
        self.memory[16:16+len(data)] = data
        self.memory[4:8] = struct.pack('<I',self.sequence)
        self.pulse()

    def pulse(self):
        self.memory[12:16]=struct.pack("<I",int(time.monotonic()*1000)&0xffffffff)

    def close(self):
        self.memory.close();self.file.close()


class Reader:
    def __init__(self, path):
        self.file = Path(path).open('rb')
        try:self.memory = mmap.mmap(self.file.fileno(),SIZE,access=mmap.ACCESS_READ)
        except Exception:self.file.close();raise
        self.sequence = None
        self.value = None

    def read(self):
        magic, sequence, length = struct.unpack('<4sII',self.memory[:12])
        if magic!=MAGIC or sequence&1 or length>SIZE-16:return self.value
        if sequence==self.sequence:return self.value
        data=self.memory[16:16+length]
        if struct.unpack('<I',self.memory[4:8])[0]!=sequence:return self.value
        try:value=json.loads(data)
        except ValueError:return self.value
        self.sequence,self.value=sequence,value
        return value

    def fresh(self):
        tick=struct.unpack('<I',self.memory[12:16])[0]
        return ((int(time.monotonic()*1000)-tick)&0xffffffff)<2500

    def close(self):
        self.memory.close();self.file.close()
