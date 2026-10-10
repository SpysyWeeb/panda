"""Exact-source heartbeat slices plus host health decoding; no physical USB device."""
import ctypes
import inspect
import subprocess
from pathlib import Path
from unittest.mock import Mock

import opendbc
import pytest
from panda import Panda

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def panda():
  p = Panda.__new__(Panda)
  p.health_version = Panda.HEALTH_PACKET_VERSION
  p._handle = Mock()
  return p


@pytest.mark.parametrize("lateral", [False, True])
@pytest.mark.parametrize("resets", [0, 1 << 7, 1 << 8, (1 << 7) | (1 << 8)])
def test_health_lateral_and_reset_flags(panda, lateral, resets):
  values = [0] * len(Panda.HEALTH_STRUCT.unpack(bytes(Panda.HEALTH_STRUCT.size)))
  values[8] = resets | ((1 << 9) if lateral else 0)
  panda._handle.controlRead.return_value = Panda.HEALTH_STRUCT.pack(*values)
  h = panda.health()
  assert h.get("lateral_allowed", False) == lateral
  assert h["nmi_reset"] == bool(resets & (1 << 7))
  assert h["hardfault_reset"] == bool(resets & (1 << 8))
  assert not h["controls_allowed"]


def test_python_heartbeat_transport(panda):
  assert "engaged_aol" in inspect.signature(Panda.send_heartbeat).parameters
  panda.send_heartbeat(False, engaged_aol=True)
  panda._handle.controlWrite.assert_called_with(Panda.REQUEST_OUT, 0xf3, False, True, b'')
  panda.send_heartbeat()
  panda._handle.controlWrite.assert_called_with(Panda.REQUEST_OUT, 0xf3, True, False, b'')


@pytest.fixture(scope="module")
def native(tmp_path_factory):
  # Compile verbatim transport case and 1Hz heartbeat logic against this exact
  # opendbc checkout. Only board I/O and mode-switch side effects are stubbed.
  comms = (ROOT / "board/main_comms.h").read_text()
  receive = comms[comms.index("    case 0xf3:"):comms.index("    // **** 0xf6:")]
  main = (ROOT / "board/main.c").read_text()
  tick = main[main.index("      // exit controls allowed if unused"):main.index("      // check registers")]
  flags = comms[comms.index("  health->flags_pkt ="):comms.index("  health->safety_tx_blocked_pkt")]
  source = r'''
#include "opendbc/safety/tests/libsafety/safety.c"
#include "board/health.h"
#define HEARTBEAT_IGNITION_CNT_ON 5U
#define HEARTBEAT_IGNITION_CNT_OFF 2U
uint32_t heartbeat_counter = 0U;
bool heartbeat_lost = false, heartbeat_disabled = false, power_save_enabled = false;
bool bootkick_reset_triggered = false;
uint16_t reset_flags = 0U;
void noop(unsigned int x) { (void)x; }
void print(const char *s) { (void)s; }
void puth(unsigned int x) { (void)x; }
bool yes(void) { return true; }
bool harness_check_ignition(void) { return false; }
void set_power_save_state(bool b) { power_save_enabled = b; }
void fan_set_power(unsigned int x) { (void)x; }
struct { void (*set_ir_power)(unsigned int); bool (*read_som_gpio)(void); } board = {noop, yes}, *current_board = &board;
void set_safety_mode(uint16_t mode, uint16_t param) { set_safety_hooks(mode, param); }
bool is_car_safety_mode(uint16_t mode) { return mode != SAFETY_SILENT; }
void receive(uint16_t p1, uint16_t p2) {
  struct { uint16_t param1, param2; } request = {p1, p2}, *req = &request;
  switch (0xf3) {
''' + receive + r'''
  }
}
void tick(void) {
  bool started = true;
  uint32_t controls_allowed_countdown = 0U, siren_countdown = 0U;
  heartbeat_counter++;
''' + tick + r'''
}
uint16_t health_flags(bool lateral, uint16_t resets) {
  struct health_t packet, *health = &packet;
  lateral_allowed = lateral;
  reset_flags = resets;
''' + flags + r'''
  return health->flags_pkt;
}
void reset_test(void) {
  set_safety_hooks(SAFETY_HYUNDAI, 0);
  alternative_experience = ALT_EXP_AOL_ENABLE;
  heartbeat_counter = 0U;
  heartbeat_disabled = false;
  heartbeat_lost = false;
  power_save_enabled = false;
  lateral_allowed = true;
}
'''
  directory = tmp_path_factory.mktemp("aol_native")
  cfile, so = directory / "aol.c", directory / "aol.so"
  cfile.write_text(source)
  subprocess.run(["cc", "-shared", "-fPIC", "-std=gnu11", "-Werror", "-DALLOW_DEBUG", "-I", str(ROOT),
                  "-I", str(opendbc.INCLUDE_PATH), str(cfile), "-o", str(so)], check=True)
  lib = ctypes.CDLL(str(so))
  lib.get_lateral_allowed.restype = ctypes.c_bool
  lib.health_flags.restype = ctypes.c_uint16
  return lib


def test_native_heartbeat_valid_false_and_invalid(native):
  for value in (0, 2, 65535):
    native.reset_test()
    native.receive(0, 1)
    for _ in range(3):
      native.receive(0, 1)
      native.tick()
    assert native.get_lateral_allowed()
    native.receive(0, value)
    for _ in range(3):
      native.receive(0, value)
      native.tick()
    assert not native.get_lateral_allowed()


def test_native_heartbeat_lost_enters_silent(native):
  native.reset_test()
  native.receive(0, 1)
  for _ in range(5):
    native.tick()
  assert native.get_current_safety_mode() == 0
  assert not native.get_lateral_allowed()


def test_native_health_bit9_preserves_resets(native):
  for resets in (0, 1 << 7, 1 << 8, (1 << 7) | (1 << 8)):
    for lateral in (False, True):
      native.reset_test()
      assert native.health_flags(lateral, resets) == (resets | (int(lateral) << 9))
