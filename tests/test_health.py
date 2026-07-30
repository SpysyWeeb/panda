#!/usr/bin/env python3
import unittest

from panda import Panda


class FakeHandle:
  def __init__(self, health_packet=b""):
    self.health_packet = health_packet
    self.control_reads = []
    self.control_writes = []

  def controlRead(self, request_type, request, value, index, length):
    self.control_reads.append((request_type, request, value, index, length))
    return self.health_packet

  def controlWrite(self, request_type, request, value, index, data):
    self.control_writes.append((request_type, request, value, index, data))


class TestHealthPacket(unittest.TestCase):
  def setUp(self):
    self.panda = object.__new__(Panda)
    self.panda.health_version = Panda.HEALTH_PACKET_VERSION

  def test_combined_health_layout(self):
    values = [0] * 28
    values[18] = 0.5
    values[26] = 1
    values[27] = 42.5
    self.panda._handle = FakeHandle(Panda.HEALTH_STRUCT.pack(*values))

    health = self.panda.health()

    self.assertEqual(Panda.HEALTH_STRUCT.size, 64)
    self.assertEqual(health["lateral_allowed"], 1)
    self.assertEqual(health["temperature"], 42.5)
    self.assertEqual(self.panda._handle.control_reads[-1][-1], Panda.HEALTH_STRUCT.size)

  def test_aol_heartbeat_parameter(self):
    self.panda._handle = FakeHandle()

    self.panda.send_heartbeat(engaged=True, engaged_aol=True)

    self.assertEqual(
      self.panda._handle.control_writes,
      [(Panda.REQUEST_OUT, 0xf3, True, True, b"")],
    )


if __name__ == "__main__":
  unittest.main()
