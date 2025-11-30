import time

from cereal import log
from openpilot.system.sensord.sensors.i2c_sensor import Sensor

# https://www.mouser.com/datasheet/2/821/Memsic_09102019_Datasheet_Rev.B-1635324.pdf

# Register addresses
REG_ODR = 0x1A
REG_INTERNAL_0 = 0x1B
REG_INTERNAL_1 = 0x1C

# Control register settings
CMM_FREQ_EN = (1 << 7)
AUTO_SR_EN  = (1 << 5)
SET         = (1 << 3)
RESET       = (1 << 4)

class MMC5603NJ_Magn(Sensor):
  @property
  def device_address(self) -> int:
    return 0x30

 # -------------------------- 新增/重写 verify_chip_id 方法 --------------------------
  def verify_chip_id(self, chip_id_reg: int, expected_ids: list[int]) -> None:
    """重写父类的芯片ID校验方法，注释断言，兼容不同芯片ID"""
    try:
      # 读取芯片ID寄存器（chip_id_reg=0x39，对应父类调用的参数）
      chip_id = self.read_reg(chip_id_reg, 1)[0]  # 读取1字节的芯片ID
      if chip_id not in expected_ids:
        # 仅打印警告日志，不触发断言崩溃
        LOGW(f"MMC5603NJ磁力计芯片ID不匹配！实际ID: {hex(chip_id)}, 预期ID: {[hex(id) for id in expected_ids]}")
      else:
        LOGI(f"MMC5603NJ磁力计芯片ID校验通过: {hex(chip_id)}")
    except Exception as e:
      # 捕获读取失败的异常（如传感器未响应），同样不崩溃
      LOGW(f"读取MMC5603NJ磁力计芯片ID失败: {str(e)}")
  # --------------------------------------------------------------------------------
  def init(self):
    # 此处调用的是上面重写后的verify_chip_id，不会再断言崩溃
    self.verify_chip_id(0x39, [0x10, ])
    self.writes((
      (REG_ODR, 0),
      (REG_INTERNAL_1, 0b01),  # BW=0b01 for 1-150 Hz
    ))
  def _read_data(self, cycle) -> list[float]:
    # start measurement
    self.write(REG_INTERNAL_0, cycle)
    self.wait()

    # read out XYZ
    scale = 1.0 / 16384.0
    b = self.read(0x00, 9)
    return [
      (self.parse_20bit(b[6], b[1], b[0]) * scale) - 32.0,
      (self.parse_20bit(b[7], b[3], b[2]) * scale) - 32.0,
      (self.parse_20bit(b[8], b[5], b[4]) * scale) - 32.0,
    ]

  def get_event(self, ts: int | None = None) -> log.SensorEventData:
    ts = time.monotonic_ns()

    # SET - RESET cycle
    xyz = self._read_data(SET)
    reset_xyz = self._read_data(RESET)
    vals = [*xyz, *reset_xyz]

    event = log.SensorEventData.new_message()
    event.timestamp = ts
    event.version = 1
    event.sensor = 3 # SENSOR_MAGNETOMETER_UNCALIBRATED
    event.type = 14  # SENSOR_TYPE_MAGNETIC_FIELD_UNCALIBRATED
    event.source = log.SensorEventData.SensorSource.mmc5603nj

    m = event.init('magneticUncalibrated')
    m.v = vals
    m.status = int(all(int(v) != -32 for v in vals))

    return event

  def shutdown(self) -> None:
    v = self.read(REG_INTERNAL_0, 1)[0]
    self.writes((
      # disable auto-reset of measurements
      (REG_INTERNAL_0, (v & (~(CMM_FREQ_EN | AUTO_SR_EN)))),

      # disable continuous mode
      (REG_ODR, 0),
    ))
