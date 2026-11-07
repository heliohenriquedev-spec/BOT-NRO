"""Local rendering of the observed Byakugan status; never changes server-side character state."""
import json
import struct
import time

from .packet_reader import message_length

EFFECT = 184  # toggled by NRO item 19002 in the recorded equip/unequip comparison


class VisionConfig:
    def __init__(self):self.next_poll=0;self.enabled=False

    def __call__(self):
        now=time.monotonic()
        if now>=self.next_poll:
            self.next_poll=now+.25
            from .rcx_settings import FILE
            try:self.enabled=json.loads(FILE.read_text(encoding='utf-8')).get('client_vision',False) is True
            except (OSError,ValueError,AttributeError):self.enabled=False
        return self.enabled


class ClientVision:
    def __init__(self,account,player_id,enabled):
        self.account=account;self.player_id=player_id;self.enabled=enabled
        self.pending=bytearray();self.started=False;self.passthrough=False
        self.ready=False;self.real_active=False;self.applied=None
        self.error=None;self.local_updates=0

    @classmethod
    def for_account(cls,account,enabled):
        # Map actors use the account ID, not the character-selection database ID.
        return cls(account,int.from_bytes(account,'little') if account else None,enabled)

    def diagnostic(self):
        return dict(enabled=self.enabled(),player_id=self.player_id,ready=self.ready,
                    applied=self.applied,real_active=self.real_active,
                    local_updates=self.local_updates,framing_error=self.error)

    def packet(self,active):
        self.local_updates+=1
        return struct.pack('<HHIB',0x196,EFFECT,self.player_id,int(active))

    def feed(self,data):
        if self.passthrough:return data
        self.pending.extend(data);output=bytearray();offset=0
        if not self.started:
            if len(self.pending)<4:return b''
            self.started=True
            if self.account and self.pending[:4]==self.account:output.extend(self.pending[:4]);offset=4
        while offset<len(self.pending):
            try:size=message_length(self.pending,offset)
            except (ValueError,OSError) as exc:
                self.error=str(exc)
                self.passthrough=True;output.extend(self.pending[offset:]);offset=len(self.pending);break
            if size is None or offset+size>len(self.pending):break
            packet=bytes(self.pending[offset:offset+size]);offset+=size
            opcode=struct.unpack_from('<H',packet)[0]
            enabled=self.enabled()
            if opcode==0x73:self.ready=True;self.applied=None
            elif opcode in (0x91,0x92):self.ready=False;self.applied=None
            elif opcode in (0x119,0x229) and len(packet)>=6 and struct.unpack_from('<I',packet,2)[0]==self.player_id:
                self.ready=True;self.applied=None
            if (opcode==0x196 and len(packet)==9 and struct.unpack_from('<H',packet,2)[0]==EFFECT
                and struct.unpack_from('<I',packet,4)[0]==self.player_id):
                self.real_active=bool(packet[8]);self.ready=True
                active=self.real_active or enabled
                packet=packet[:8]+bytes([int(active)]);self.applied=active
            output.extend(packet)
            if self.ready and self.player_id:
                if enabled and self.applied is not True:
                    output.extend(self.packet(True));self.applied=True
                elif not enabled and self.applied is True and not self.real_active:
                    output.extend(self.packet(False));self.applied=False
        del self.pending[:offset]
        return bytes(output)

    def flush(self):
        data=bytes(self.pending);self.pending.clear();return data
