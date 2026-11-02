"""REDE-10: consumo ETW nativo, Win64. Nenhuma instalação de driver.

Layout: Microsoft EVENT_TRACE_LOGFILEW / EVENT_RECORD.
Payload PktMon 160 versão 0 conferido contra o manifesto local e ETL real.
"""
from __future__ import annotations

import ctypes as C
from pathlib import Path
import struct
import uuid

U16, U32, U64, I64 = C.c_uint16, C.c_uint32, C.c_uint64, C.c_int64
GUID = C.c_ubyte * 16
PROVIDER = uuid.UUID('4d4f80d9-c8bd-4d73-bb5b-19c90402c5ac').bytes_le


class Descriptor(C.Structure):
    _fields_ = [('id', U16), ('version', C.c_ubyte), ('channel', C.c_ubyte),
                ('level', C.c_ubyte), ('opcode', C.c_ubyte), ('task', U16), ('keywords', U64)]


class Header(C.Structure):
    _fields_ = [('size', U16), ('type', U16), ('flags', U16), ('property', U16),
                ('thread', U32), ('process', U32), ('time', I64), ('provider', GUID),
                ('descriptor', Descriptor), ('processor_time', U64), ('activity', GUID)]


class Record(C.Structure):
    _fields_ = [('header', Header), ('buffer_context', U32), ('extended_count', U16),
                ('length', U16), ('extended', C.c_void_p), ('data', C.c_void_p), ('context', C.c_void_p)]


class TraceEvent(C.Structure):
    _fields_ = [('header', C.c_ubyte * 48), ('instance', U32), ('parent', U32),
                ('parent_guid', GUID), ('data', C.c_void_p), ('length', U32), ('context', U32)]


class LogHeader(C.Structure):
    _fields_ = [('buffer_size', U32), ('version', U32), ('provider_version', U32),
                ('processors', U32), ('end_time', I64), ('timer_resolution', U32),
                ('max_file_size', U32), ('log_mode', U32), ('buffers_written', U32),
                ('instance', GUID), ('logger_name', C.c_void_p), ('log_name', C.c_void_p),
                ('time_zone', C.c_ubyte * 172), ('boot_time', I64), ('frequency', I64),
                ('start_time', I64), ('reserved', U32), ('buffers_lost', U32)]


class Logfile(C.Structure):
    _fields_ = [('filename', C.c_wchar_p), ('logger', C.c_wchar_p), ('current_time', I64),
                ('buffers_read', U32), ('mode', U32), ('current_event', TraceEvent),
                ('header', LogHeader), ('buffer_callback', C.c_void_p), ('buffer_size', U32),
                ('filled', U32), ('events_lost', U32), ('event_callback', C.c_void_p),
                ('kernel_trace', U32), ('context', C.c_void_p)]


def active_session_file(logger='PktMon'):
    """Query only; None means no session. Empty string means a real-time session."""
    if C.sizeof(C.c_void_p) != 8:
        raise RuntimeError('Requer Windows de 64 bits')
    api = C.WinDLL('advapi32', use_last_error=True)
    api.QueryTraceW.argtypes = [U64, C.c_wchar_p, C.c_void_p]
    api.QueryTraceW.restype = U32
    buffer = C.create_string_buffer(65536)
    # EVENT_TRACE_PROPERTIES Win64: size 120, string offsets at 112 and 116.
    struct.pack_into('<I', buffer, 0, len(buffer))
    struct.pack_into('<II', buffer, 112, 120, 32768)
    result = api.QueryTraceW(0, logger, C.byref(buffer))
    if result == 4201:  # ERROR_WMI_INSTANCE_NOT_FOUND
        return None
    if result:
        raise C.WinError(result)
    offset = struct.unpack_from('<I', buffer, 112)[0]
    if offset < 120 or offset >= len(buffer) or offset % 2:
        raise ValueError('Metadados da sessão ETW inválidos')
    return C.wstring_at(C.addressof(buffer)+offset)


def packet_payload(raw: bytes):
    if len(raw) < 34:
        raise ValueError('Evento PktMon truncado')
    values = struct.unpack_from('<Q7H2I2H', raw)
    group, packet, appearance, direction, packet_type, component, edge, filter_id, drop, location, original, logged = values
    if original != logged or len(raw) != 34 + logged:
        raise ValueError('Payload PktMon incompleto')
    if packet_type != 1:
        return None
    return {'frame': raw[34:], 'component': component, 'group': group, 'direction': direction}


class EtwReader:
    def __init__(self, *, filename=None, logger=None, on_packet, on_loss=lambda count: None):
        if C.sizeof(C.c_void_p) != 8 or C.sizeof(Logfile) != 448 or C.sizeof(Record) != 112:
            raise RuntimeError('O leitor ETW requer Python Windows de 64 bits e ABI compatível')
        if bool(filename) == bool(logger):
            raise ValueError('Informe um ETL ou uma sessão ETW')
        self.api = C.WinDLL('advapi32', use_last_error=True)
        self.api.OpenTraceW.argtypes = [C.POINTER(Logfile)]
        self.api.OpenTraceW.restype = U64
        self.api.ProcessTrace.argtypes = [C.POINTER(U64), U32, C.c_void_p, C.c_void_p]
        self.api.ProcessTrace.restype = U32
        self.api.CloseTrace.argtypes = [U64]
        self.api.CloseTrace.restype = U32
        self.handle = None
        self.cancelled = False
        self.error = None
        self.log = Logfile()
        self.log.filename = str(Path(filename).resolve()) if filename else None
        self.log.logger = logger
        self.log.mode = 0x10000000 | (0x100 if logger else 0)  # EVENT_RECORD / REAL_TIME
        self.last_loss = 0

        def event_callback(pointer):
            if self.cancelled:
                return
            try:
                record = C.cast(pointer, C.POINTER(Record)).contents
                if bytes(record.header.provider) != PROVIDER or record.header.descriptor.id != 160:
                    return
                if record.header.descriptor.version != 0:
                    raise ValueError('Versão de evento PktMon não suportada')
                packet = packet_payload(C.string_at(record.data, record.length))
                if packet is not None:
                    packet['time'] = (record.header.time - 116444736000000000) / 10_000_000
                    on_packet(packet)
            except BaseException as exc:
                self.error, self.cancelled = exc, True

        def buffer_callback(pointer):
            try:
                log = C.cast(pointer, C.POINTER(Logfile)).contents
                lost = int(log.events_lost) + int(log.header.buffers_lost)
                if lost > self.last_loss:
                    on_loss(lost)
                    self.last_loss = lost
            except BaseException as exc:
                self.error, self.cancelled = exc, True
            return 0 if self.cancelled else 1

        self.event_callback = C.WINFUNCTYPE(None, C.c_void_p)(event_callback)
        self.buffer_callback = C.WINFUNCTYPE(U32, C.c_void_p)(buffer_callback)
        self.log.event_callback = C.cast(self.event_callback, C.c_void_p)
        self.log.buffer_callback = C.cast(self.buffer_callback, C.c_void_p)

    def open(self):
        self.handle = int(self.api.OpenTraceW(C.byref(self.log)))
        if self.handle == 0xffffffffffffffff:
            self.handle = None
            raise C.WinError(C.get_last_error())

    def process(self):
        if self.handle is None:
            self.open()
        value = U64(self.handle)
        result = self.api.ProcessTrace(C.byref(value), 1, None, None)
        if self.error:
            raise self.error
        if result not in (0, 1223):
            raise C.WinError(result)

    def close(self):
        self.cancelled = True
        if self.handle is not None:
            self.api.CloseTrace(U64(self.handle))
            self.handle = None
