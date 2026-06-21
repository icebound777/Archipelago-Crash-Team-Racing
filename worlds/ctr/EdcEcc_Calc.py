from enum import Enum

SECTOR_SIZE = 2352


class CodeType(Enum):
    PCode = 0
    QCode = 1


class LookUpTables:
    ecc_f = bytearray(256)
    ecc_b = bytearray(256)
    edc = [0] * 256

    def __init__(self):
        for i in range(256):
            j = (i << 1) ^ (0x11D if i & 0x80 else 0)
            self.ecc_f[i] = j
            self.ecc_b[i ^ j] = i
            edc = i

            for j in range(8):
                edc = (edc >> 1) ^ (0xD8018001 if edc & 1 else 0)

            self.edc[i] = edc


def _compute_edc_block(luts: LookUpTables, sector) -> int:
    edc = 0
    for b in sector:
        edc = (edc >> 8) ^ luts.edc[(edc ^ b) & 0xFF]

    return edc


def _get_computed_ecc_block(luts: LookUpTables, sector, code_type: CodeType) -> bytearray:
    if code_type == CodeType.PCode:
        (major_count, minor_count, major_mult, minor_inc) = (86, 24, 2, 86)
    else:
        (major_count, minor_count, major_mult, minor_inc) = (52, 43, 86, 88)

    size = major_count * minor_count
    block = bytearray(major_count * 2)

    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        ecc_a = 0
        ecc_b = 0

        for _ in range(minor_count):
            temp = sector[index]
            index += minor_inc
            if index >= size:
                index -= size

            ecc_a ^= temp
            ecc_b ^= temp
            ecc_a = luts.ecc_f[ecc_a]

        ecc_a = luts.ecc_b[luts.ecc_f[ecc_a] ^ ecc_b]
        block[major] = ecc_a
        block[major + major_count] = ecc_a ^ ecc_b

    return block


def _generate_ecc(luts: LookUpTables, sector, zeroaddress: bool):
    if zeroaddress:
        address = sector[12:12+4]
        sector[12:12+4] = [0] * 4

    # Generate P Code
    p_code = _get_computed_ecc_block(luts, sector[0xC:], CodeType.PCode)
    sector[0x81C:0x81C+len(p_code)] = p_code

    # Generate Q Code
    q_code = _get_computed_ecc_block(luts, sector[0xC:], CodeType.QCode)
    sector[0x8C8:0x8C8+len(q_code)] = q_code

    if zeroaddress:
        sector[12:12+4] = address


def _ecc_edc_generate(luts: LookUpTables, sector):
    SYNCHEADER = bytes([0, 255, 255, 255, 255, 255,
                       255, 255, 255, 255, 255, 0])
    sector[0:len(SYNCHEADER)] = SYNCHEADER

    mode = sector[0xF]

    if mode == 0:
        sector[0x10:0x10+0x920] = [0] * 0x920
    elif mode == 1:
        edc = _compute_edc_block(luts, sector[:0x810])
        sector[0x810:0x810+4] = edc.to_bytes(4, byteorder="little")
        sector[0x814:0x814+8] = [0] * 8
        _generate_ecc(luts, sector, False)
    elif mode == 2:
        form = sector[0x12] & 0x20

        if not form:
            # Form 1
            edc = _compute_edc_block(luts, sector[0x10:0x10+0x808])
            sector[0x818:0x818+4] = edc.to_bytes(4, byteorder="little")
            _generate_ecc(luts, sector, True)
        else:
            # Form 2
            edc = _compute_edc_block(luts, sector[0x10:0x10+0x91C])
            sector[0x92C:0x92C+4] = edc.to_bytes(4, byteorder="little")


def full_recalc_edc_ecc(file_as_bytes: bytearray) -> bytearray:
    file_size = len(file_as_bytes)
    if file_size % SECTOR_SIZE != 0:
        raise ValueError(f"File is not in {SECTOR_SIZE} bytes sectors")

    sector_count = int(file_size / SECTOR_SIZE)
    luts = LookUpTables()

    for sector_no in range(16, sector_count):
        start = sector_no * SECTOR_SIZE

        sector = bytearray(file_as_bytes[start:start+SECTOR_SIZE])

        _ecc_edc_generate(luts, sector)

        file_as_bytes[start:start+SECTOR_SIZE] = sector

    return file_as_bytes
