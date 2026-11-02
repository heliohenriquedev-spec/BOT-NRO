# Copyright (c) rAthena Dev Teams; Python adaptation for this project.
# Source: rAthena src/common/des.cpp; license: third_party/rathena/LICENCE.
# Standard GRF file-format support, read-only.
IP_TABLE = [58, 50, 42, 34, 26, 18, 10, 2, 60, 52, 44, 36, 28, 20, 12, 4, 62, 54, 46, 38, 30, 22, 14, 6, 64, 56, 48, 40, 32, 24, 16, 8, 57, 49, 41, 33, 25, 17, 9, 1, 59, 51, 43, 35, 27, 19, 11, 3, 61, 53, 45, 37, 29, 21, 13, 5, 63, 55, 47, 39, 31, 23, 15, 7]
FP_TABLE = [40, 8, 48, 16, 56, 24, 64, 32, 39, 7, 47, 15, 55, 23, 63, 31, 38, 6, 46, 14, 54, 22, 62, 30, 37, 5, 45, 13, 53, 21, 61, 29, 36, 4, 44, 12, 52, 20, 60, 28, 35, 3, 43, 11, 51, 19, 59, 27, 34, 2, 42, 10, 50, 18, 58, 26, 33, 1, 41, 9, 49, 17, 57, 25]
TP_TABLE = [16, 7, 20, 21, 29, 12, 28, 17, 1, 15, 23, 26, 5, 18, 31, 10, 2, 8, 24, 14, 32, 27, 3, 9, 19, 13, 30, 6, 22, 11, 4, 25]
S_TABLE = [239, 3, 65, 253, 216, 116, 30, 71, 38, 239, 251, 34, 179, 216, 132, 30, 57, 172, 167, 96, 98, 193, 205, 186, 92, 150, 144, 89, 5, 59, 122, 133, 64, 253, 30, 200, 231, 138, 139, 33, 218, 67, 100, 159, 45, 20, 177, 114, 245, 91, 200, 182, 156, 55, 118, 236, 57, 160, 163, 5, 82, 110, 15, 217, 167, 221, 13, 120, 158, 11, 227, 149, 96, 54, 54, 79, 249, 96, 90, 163, 17, 36, 210, 135, 200, 82, 117, 236, 187, 193, 76, 186, 36, 254, 143, 25, 218, 19, 102, 175, 73, 208, 144, 6, 140, 106, 251, 145, 55, 141, 13, 120, 191, 73, 17, 244, 35, 229, 206, 59, 85, 188, 162, 87, 232, 34, 116, 206, 44, 234, 193, 191, 74, 36, 31, 194, 121, 71, 162, 124, 182, 217, 104, 21, 128, 86, 93, 1, 51, 253, 244, 174, 222, 48, 7, 155, 229, 131, 155, 104, 73, 180, 46, 131, 31, 194, 181, 124, 162, 25, 216, 229, 124, 47, 131, 218, 247, 107, 144, 254, 196, 1, 90, 151, 97, 166, 61, 64, 11, 88, 230, 61, 77, 209, 178, 15, 40, 189, 228, 120, 246, 74, 15, 147, 139, 23, 209, 164, 58, 236, 201, 53, 147, 86, 126, 203, 85, 32, 160, 254, 108, 137, 23, 98, 23, 98, 75, 177, 180, 222, 209, 135, 201, 20, 60, 74, 126, 168, 226, 125, 160, 159, 246, 92, 106, 9, 141, 240, 15, 227, 83, 37, 149, 54, 40, 203]
def _permute(value, table, bits):
    out = 0
    for position in table:
        out = (out << 1) | ((value >> (bits-position)) & 1)
    return out


def decode_block(raw):
    b = _permute(int.from_bytes(raw, 'big'), IP_TABLE, 64).to_bytes(8, 'big')
    r = b[4:]
    e = [((r[3]<<5)|(r[0]>>3))&63, ((r[0]<<1)|(r[1]>>7))&63,
         ((r[0]<<5)|(r[1]>>3))&63, ((r[1]<<1)|(r[2]>>7))&63,
         ((r[1]<<5)|(r[2]>>3))&63, ((r[2]<<1)|(r[3]>>7))&63,
         ((r[2]<<5)|(r[3]>>3))&63, ((r[3]<<1)|(r[0]>>7))&63]
    sub = bytes((S_TABLE[i*64+e[2*i]]&240)|(S_TABLE[i*64+e[2*i+1]]&15) for i in range(4))
    left = int.from_bytes(b[:4], 'big') ^ _permute(int.from_bytes(sub, 'big'), TP_TABLE, 32)
    return _permute((left<<32)|int.from_bytes(r, 'big'), FP_TABLE, 64).to_bytes(8, 'big')


def decode_header(data):
    result = bytearray(data)
    for offset in range(0, min(160, len(result)//8*8), 8):
        result[offset:offset+8] = decode_block(result[offset:offset+8])
    return bytes(result)


def decode_mixed(data, compressed_size):
    """REDE-54: standard GRF mixed blocks; rAthena grfio.cpp (GPLv3)."""
    digits = len(str(max(0, compressed_size)))
    cycle = 1 if digits < 3 else digits+1 if digits < 5 else digits+9 if digits < 7 else digits+15
    substitutions = {0:43,43:0,108:128,128:108,1:104,104:1,72:119,119:72,
                     96:255,255:96,185:192,192:185,254:235,235:254}
    result = bytearray(decode_header(data))
    plain_index = -1
    for block in range(20, len(result)//8):
        offset = block*8
        if block % cycle == 0:
            result[offset:offset+8] = decode_block(result[offset:offset+8])
            continue
        plain_index += 1
        if plain_index and plain_index % 7 == 0:
            raw = result[offset:offset+8]
            result[offset:offset+8] = bytes([raw[3],raw[4],raw[6],raw[0],raw[1],raw[2],raw[5],substitutions.get(raw[7],raw[7])])
    return bytes(result)
