#!/usr/bin/env python3
import random
import unittest
from unittest.mock import Mock

from panda import Panda, pack_can_buffer, unpack_can_buffer, DLC_TO_LEN

class PandaTestPackUnpack(unittest.TestCase):
  def test_lateral_allowed_health_flag(self):
    panda = Panda.__new__(Panda)
    panda.health_version = Panda.HEALTH_PACKET_VERSION
    values = [0] * len(Panda.HEALTH_STRUCT.unpack(bytes(Panda.HEALTH_STRUCT.size)))
    values[8] = Panda.HEALTH_FLAG_LATERAL_ALLOWED
    panda._handle = Mock()
    panda._handle.controlRead.return_value = Panda.HEALTH_STRUCT.pack(*values)

    self.assertTrue(panda.health()["lateral_allowed"])

  def test_panda_lib_pack_unpack(self):
    overflow_buf = b''

    to_pack = []
    for _ in range(10000):
      address = random.randint(1, (1 << 29) - 1)
      data = bytes([random.getrandbits(8) for _ in range(DLC_TO_LEN[random.randrange(0, len(DLC_TO_LEN))])])
      to_pack.append((address, data, 0))

    packed = pack_can_buffer(to_pack)
    unpacked = []
    for dat in packed:
      msgs, overflow_buf = unpack_can_buffer(overflow_buf + dat)
      unpacked.extend(msgs)

    self.assertEqual(unpacked, to_pack)

if __name__ == "__main__":
  unittest.main()
