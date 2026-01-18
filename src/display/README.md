# Display Module

This module manages the 1.27" RGB OLED display (SSD1351) for the Casper Pi application.

## Hardware

### Display: 1.27" RGB OLED (SSD1351)
- 128x128 pixel resolution
- SPI interface
- RGB color support

## Wiring Guide

### All 6 Display Connections:

#### Power & Ground (2 pins):
1. **VCC** (Power) → Raspberry Pi **3.3V** (Pin 1 or Pin 17)
2. **GND** (Ground) → Raspberry Pi **GND** (Pin 6, 9, 14, 20, 25, 30, 34, or 39)

#### SPI Data Pins (2 pins - these are FIXED by SPI):
3. **DIN/MOSI** (Data Input) → Raspberry Pi **GPIO 10 / MOSI** (Pin 19)
4. **SCL/SCLK** (Clock) → Raspberry Pi **GPIO 11 / SCLK** (Pin 23)

#### Control Pins (3 pins - you can choose these):
5. **CS** (Chip Select) → Raspberry Pi **GPIO 18** (Pin 12) - *You can change this*
6. **DC** (Data/Command) → Raspberry Pi **GPIO 19** (Pin 35) - *You can change this*
7. **RST** (Reset) → Raspberry Pi **GPIO 20** (Pin 38) - *You can change this*

## Current Configuration

```python
CS_PIN = board.D18   # GPIO 18
DC_PIN = board.D19   # GPIO 19
RST_PIN = board.D20  # GPIO 20
```

## Pin Summary

| Display Pin | Raspberry Pi Pin | GPIO Number | Can Change? |
|-------------|------------------|------------|-------------|
| VCC         | Pin 1 or 17      | 3.3V       | No (must be 3.3V) |
| GND         | Any GND pin      | GND        | No (must be GND) |
| DIN/MOSI    | Pin 19           | GPIO 10    | No (SPI fixed) |
| SCL/SCLK    | Pin 23           | GPIO 11    | No (SPI fixed) |
| CS          | Pin 12           | GPIO 18    | **YES** (change in script) |
| DC          | Pin 35           | GPIO 19    | **YES** (change in script) |
| RST         | Pin 38           | GPIO 20    | **YES** (change in script) |

## Changing Control Pins

To use different pins for CS/DC/RST, edit the display manager code and change:
```python
CS_PIN = board.D18   # Change D18 to D21, D22, D23, etc.
DC_PIN = board.D19   # Change D19 to D21, D22, D23, etc.
RST_PIN = board.D20  # Change D20 to D21, D22, D23, etc.
```

Available GPIO pins you can use: 18, 19, 20, 21, 22, 23, 24, 25, 26, 27

## Module Structure

- `manager.py` - Main display manager with state handling
- `states.py` - Display state definitions
- `tools.py` - Display tool registry for Gemini integration
- `visualizations.py` - Visualization functions for different states

