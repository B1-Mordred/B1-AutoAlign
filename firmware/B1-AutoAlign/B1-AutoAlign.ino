/*
 * B1-AutoAlign - small ESP32 controller for a motorized polar-alignment base
 *
 * Hardware target: OpenAstroExplorer board v1 pinout
 * Control:         19200-baud Meade-style serial subset used by Ekos/INDI
 * License:         MIT (see LICENSE)
 *
 * This is a clean PA-only implementation.  It intentionally contains no
 * RA/DEC tracking, GoTo, parking, focuser, GPS, display, Wi-Fi or guiding.
 */

#include <Arduino.h>
#include <Preferences.h>
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

namespace Config
{
constexpr uint32_t SERIAL_BAUD = 19200;

// Official OpenAstroExplorer board v1 pin map.
constexpr uint8_t ALT_STEP_PIN = 13;
constexpr uint8_t ALT_DIR_PIN  = 23;
constexpr uint8_t ALT_EN_PIN   = 4;
constexpr uint8_t AZ_STEP_PIN  = 18;
constexpr uint8_t AZ_DIR_PIN   = 19;
constexpr uint8_t AZ_EN_PIN    = 32;

// A4988-style enables are active low.
constexpr bool ENABLE_ACTIVE_LOW = true;

// Change one of these only if a positive command moves that axis in the
// mechanically negative direction.  Positive ALT must move up from bottom.
constexpr bool ALT_DIR_INVERT = false;
constexpr bool AZ_DIR_INVERT  = false;

// Conservative PA speeds.  These are step pulses at the driver input.
constexpr float ALT_MAX_SPEED = 800.0f;
constexpr float AZ_MAX_SPEED  = 800.0f;
constexpr float ALT_ACCEL     = 500.0f;
constexpr float AZ_ACCEL      = 500.0f;
constexpr float START_SPEED   = 40.0f;
constexpr uint32_t STEP_PULSE_US = 3;
constexpr uint32_t DISABLE_DELAY_MS = 250;

// Migration defaults measured with the currently installed V1.13.16 setup.
// Calibrate these against real angular movement before automated alignment.
constexpr float DEFAULT_ALT_STEPS_PER_ARCMIN = 100.0f;
constexpr float DEFAULT_AZ_STEPS_PER_ARCMIN  = 11.0f;

// The present physical position was established as the ALT bottom.  On a
// fresh Preferences namespace the firmware therefore starts at ALT=0 and
// rejects all negative ALT targets.
constexpr int32_t DEFAULT_ALT_MIN = 0;
}  // namespace Config

enum class MoveResult : uint8_t
{
    Accepted,
    MinLimit,
    MaxLimit,
    Busy
};

class StepDirAxis
{
  public:
    StepDirAxis(const char *axisName, uint8_t stepPin, uint8_t dirPin, uint8_t enablePin, bool invertDirection,
                float maxStepRate, float acceleration)
        : name(axisName), step(stepPin), dir(dirPin), enable(enablePin), invertDir(invertDirection),
          maxSpeed(maxStepRate), accel(acceleration)
    {
    }

    void begin(int32_t savedPosition)
    {
        pinMode(step, OUTPUT);
        pinMode(dir, OUTPUT);
        pinMode(enable, OUTPUT);
        digitalWrite(step, LOW);
        setDriverEnabled(false);
        current = savedPosition;
        target  = savedPosition;
    }

    void setLimits(bool minimumEnabled, int32_t minimum, bool maximumEnabled, int32_t maximum)
    {
        minEnabled = minimumEnabled;
        minPosition = minimum;
        maxEnabled = maximumEnabled;
        maxPosition = maximum;
    }

    MoveResult moveTo(int32_t requested)
    {
        if (isMoving())
            return MoveResult::Busy;
        if (minEnabled && requested < minPosition)
            return MoveResult::MinLimit;
        if (maxEnabled && requested > maxPosition)
            return MoveResult::MaxLimit;
        target = requested;
        if (target != current)
        {
            speed = Config::START_SPEED;
            lastStepUs = micros();
            setDriverEnabled(true);
        }
        return MoveResult::Accepted;
    }

    MoveResult moveBy(int32_t delta)
    {
        const int64_t requested = static_cast<int64_t>(current) + delta;
        if (requested < INT32_MIN || requested > INT32_MAX)
            return delta < 0 ? MoveResult::MinLimit : MoveResult::MaxLimit;
        return moveTo(static_cast<int32_t>(requested));
    }

    void stopNow()
    {
        target = current;
        speed = 0.0f;
        lastMotionMs = millis();
        setDriverEnabled(false);
    }

    void setCurrentPosition(int32_t value)
    {
        current = value;
        target = value;
        speed = 0.0f;
        lastMotionMs = millis();
    }

    bool service(uint32_t nowUs)
    {
        if (!isMoving())
        {
            if (driverEnabled && millis() - lastMotionMs >= Config::DISABLE_DELAY_MS)
                setDriverEnabled(false);
            return false;
        }

        const int64_t remaining = static_cast<int64_t>(target) - current;
        const uint32_t interval = static_cast<uint32_t>(1000000.0f / fmaxf(speed, Config::START_SPEED));
        if (static_cast<uint32_t>(nowUs - lastStepUs) < interval)
            return false;

        const int8_t sign = remaining > 0 ? 1 : -1;
        const bool directionLevel = (sign > 0) ^ invertDir;
        digitalWrite(dir, directionLevel ? HIGH : LOW);
        digitalWrite(step, HIGH);
        delayMicroseconds(Config::STEP_PULSE_US);
        digitalWrite(step, LOW);

        current += sign;
        lastStepUs = nowUs;
        lastMotionMs = millis();

        const uint64_t left = static_cast<uint64_t>(remaining > 0 ? remaining - 1 : -remaining - 1);
        const float stoppingSteps = (speed * speed) / (2.0f * accel);
        if (left == 0)
        {
            speed = 0.0f;
            return true;
        }
        if (static_cast<float>(left) <= stoppingSteps)
            speed = sqrtf(fmaxf(Config::START_SPEED * Config::START_SPEED, speed * speed - 2.0f * accel));
        else
            speed = fminf(maxSpeed, sqrtf(speed * speed + 2.0f * accel));
        return true;
    }

    bool isMoving() const { return current != target; }
    int32_t position() const { return current; }
    int32_t targetPosition() const { return target; }
    int32_t minimum() const { return minPosition; }
    int32_t maximum() const { return maxPosition; }
    bool hasMinimum() const { return minEnabled; }
    bool hasMaximum() const { return maxEnabled; }
    const char *axisName() const { return name; }

  private:
    void setDriverEnabled(bool on)
    {
        driverEnabled = on;
        const bool outputLevel = Config::ENABLE_ACTIVE_LOW ? !on : on;
        digitalWrite(enable, outputLevel ? HIGH : LOW);
    }

    const char *name;
    uint8_t step;
    uint8_t dir;
    uint8_t enable;
    bool invertDir;
    float maxSpeed;
    float accel;
    float speed = 0.0f;
    int32_t current = 0;
    int32_t target = 0;
    int32_t minPosition = 0;
    int32_t maxPosition = 0;
    bool minEnabled = false;
    bool maxEnabled = false;
    bool driverEnabled = false;
    uint32_t lastStepUs = 0;
    uint32_t lastMotionMs = 0;
};

Preferences preferences;
StepDirAxis altitude("ALT", Config::ALT_STEP_PIN, Config::ALT_DIR_PIN, Config::ALT_EN_PIN, Config::ALT_DIR_INVERT,
                     Config::ALT_MAX_SPEED, Config::ALT_ACCEL);
StepDirAxis azimuth("AZ", Config::AZ_STEP_PIN, Config::AZ_DIR_PIN, Config::AZ_EN_PIN, Config::AZ_DIR_INVERT,
                    Config::AZ_MAX_SPEED, Config::AZ_ACCEL);

float altStepsPerArcmin = Config::DEFAULT_ALT_STEPS_PER_ARCMIN;
float azStepsPerArcmin  = Config::DEFAULT_AZ_STEPS_PER_ARCMIN;
bool altMaxEnabled = false;
int32_t altMaxPosition = 0;
bool positionDirty = false;
uint32_t lastPositionChangeMs = 0;
char lastFault[32] = "NONE";

char commandBuffer[96];
size_t commandLength = 0;
bool receivingCommand = false;

void setFault(const char *fault)
{
    strncpy(lastFault, fault, sizeof(lastFault) - 1);
    lastFault[sizeof(lastFault) - 1] = '\0';
}

void markPositionDirty()
{
    positionDirty = true;
    lastPositionChangeMs = millis();
}

void persistPositions(bool force = false)
{
    if (!positionDirty && !force)
        return;
    if (altitude.isMoving() || azimuth.isMoving())
        return;
    if (!force && millis() - lastPositionChangeMs < 1500)
        return;
    preferences.putLong("altPos", altitude.position());
    preferences.putLong("azPos", azimuth.position());
    positionDirty = false;
}

void persistConfiguration()
{
    preferences.putFloat("altCal", altStepsPerArcmin);
    preferences.putFloat("azCal", azStepsPerArcmin);
    preferences.putBool("altMaxEn", altMaxEnabled);
    preferences.putLong("altMax", altMaxPosition);
}

void printMotionStatus()
{
    char motion[] = "------";
    if (azimuth.isMoving())
        motion[3] = azimuth.targetPosition() < azimuth.position() ? 'Z' : 'z';
    if (altitude.isMoving())
        motion[4] = altitude.targetPosition() < altitude.position() ? 'A' : 'a';
    Serial.printf("Parked,%s,0,0,0,000000,+900000,,#", motion);
}

void reportMoveResult(MoveResult result, bool returnAck)
{
    switch (result)
    {
        case MoveResult::Accepted:
            setFault("NONE");
            if (returnAck)
                Serial.print('1');
            break;
        case MoveResult::MinLimit:
            setFault("MIN_LIMIT");
            if (returnAck)
                Serial.print('0');
            break;
        case MoveResult::MaxLimit:
            setFault("MAX_LIMIT");
            if (returnAck)
                Serial.print('0');
            break;
        case MoveResult::Busy:
            setFault("BUSY");
            if (returnAck)
                Serial.print('0');
            break;
    }
}

bool parseFloatStrict(const char *text, float &value)
{
    if (text == nullptr || *text == '\0')
        return false;
    char *end = nullptr;
    value = strtof(text, &end);
    return end != text && *end == '\0' && isfinite(value);
}

bool parseLongStrict(const char *text, int32_t &value)
{
    if (text == nullptr || *text == '\0')
        return false;
    char *end = nullptr;
    errno = 0;
    const long parsed = strtol(text, &end, 10);
    if (end == text || *end != '\0' || errno == ERANGE || parsed < INT32_MIN || parsed > INT32_MAX)
        return false;
    value = static_cast<int32_t>(parsed);
    return true;
}

void handlePaExtension(const char *body)
{
    if (strcmp(body, "PAB") == 0)  // Mark current ALT position as bottom/zero.
    {
        if (altitude.isMoving())
        {
            Serial.print("0#");
            return;
        }
        const int32_t oldPosition = altitude.position();
        altitude.setCurrentPosition(0);
        if (altMaxEnabled)
        {
            const int64_t shiftedMaximum = static_cast<int64_t>(altMaxPosition) - oldPosition;
            if (shiftedMaximum > 0 && shiftedMaximum <= INT32_MAX)
                altMaxPosition = static_cast<int32_t>(shiftedMaximum);
            else
                altMaxEnabled = false;
        }
        altitude.setLimits(true, 0, altMaxEnabled, altMaxPosition);
        persistConfiguration();
        markPositionDirty();
        persistPositions(true);
        Serial.print("1#");
        return;
    }
    if (strcmp(body, "PAT") == 0)  // Mark current ALT position as the top limit.
    {
        if (altitude.isMoving() || altitude.position() <= altitude.minimum())
        {
            Serial.print("0#");
            return;
        }
        altMaxPosition = altitude.position();
        altMaxEnabled = true;
        altitude.setLimits(true, 0, true, altMaxPosition);
        persistConfiguration();
        Serial.print("1#");
        return;
    }
    if (strcmp(body, "PCT") == 0)  // Clear only the ALT top limit.
    {
        altMaxEnabled = false;
        altitude.setLimits(true, 0, false, 0);
        persistConfiguration();
        Serial.print("1#");
        return;
    }
    if (strcmp(body, "PGL") == 0)
    {
        Serial.printf("AZ=%ld,ALT=%ld,ALTMIN=0,ALTMAX=", static_cast<long>(azimuth.position()),
                      static_cast<long>(altitude.position()));
        if (altMaxEnabled)
            Serial.print(static_cast<long>(altMaxPosition));
        else
            Serial.print("NA");
        Serial.printf(",ACAL=%.4f,ZCAL=%.4f,FAULT=%s#", altStepsPerArcmin, azStepsPerArcmin, lastFault);
        return;
    }
    if (strncmp(body, "PCAl", 4) == 0)
    {
        float value;
        if (parseFloatStrict(body + 4, value) && value > 0.0f && value < 100000.0f)
        {
            altStepsPerArcmin = value;
            persistConfiguration();
            Serial.print("1#");
        }
        else
            Serial.print("0#");
        return;
    }
    if (strncmp(body, "PCAz", 4) == 0)
    {
        float value;
        if (parseFloatStrict(body + 4, value) && value > 0.0f && value < 100000.0f)
        {
            azStepsPerArcmin = value;
            persistConfiguration();
            Serial.print("1#");
        }
        else
            Serial.print("0#");
        return;
    }
    Serial.print("0#");
}

void processCommand(const char *command)
{
    if (command[0] != ':')
        return;
    const char *body = command + 1;

    // Identification and read-only mount compatibility.
    if (strcmp(body, "GVP") == 0) { Serial.print("B1-AutoAlign#"); return; }
    if (strcmp(body, "GVN") == 0) { Serial.print("V0.1.0#"); return; }
    if (strcmp(body, "GVF") == 0) { Serial.print("B1-AutoAlign V0.1.0#"); return; }
    if (strcmp(body, "GVD") == 0) { Serial.print("Nov 2026#"); return; }
    if (strcmp(body, "GVT") == 0) { Serial.print("00:00:00#"); return; }
    if (strcmp(body, "GR") == 0)  { Serial.print("00:00:00#"); return; }
    if (strcmp(body, "GD") == 0)  { Serial.print("+90*00:00#"); return; }
    if (strcmp(body, "GL") == 0)  { Serial.print("00:00:00#"); return; }
    if (strcmp(body, "GS") == 0)  { Serial.print("00:00:00#"); return; }
    if (strcmp(body, "GC") == 0)  { Serial.print("01/01/26#"); return; }
    if (strcmp(body, "GG") == 0)  { Serial.print("+00#"); return; }
    if (strcmp(body, "Gc") == 0)  { Serial.print("24#"); return; }
    if (strcmp(body, "GM") == 0 || strcmp(body, "GN") == 0 ||
        strcmp(body, "GO") == 0 || strcmp(body, "GP") == 0)
    {
        Serial.print("B1-AutoAlign#");
        return;
    }
    if (strcmp(body, "GT") == 0)  { Serial.print("60.0#"); return; }
    if (strcmp(body, "Gt") == 0)  { Serial.print("+00*00#"); return; }
    if (strcmp(body, "Gg") == 0)  { Serial.print("000*00#"); return; }
    if (strcmp(body, "D") == 0)   { Serial.print('#'); return; }
    if (strcmp(body, "GX") == 0)  { printMotionStatus(); return; }

    // OpenAstroTech extension queries used by the patched INDI driver.
    if (strcmp(body, "XGAA") == 0)
    {
        Serial.printf("%ld|%ld#", static_cast<long>(azimuth.position()), static_cast<long>(altitude.position()));
        return;
    }
    if (strcmp(body, "XGA") == 0) { Serial.printf("%.1f#", altStepsPerArcmin * 60.0f); return; }
    if (strcmp(body, "XGZ") == 0) { Serial.printf("%.1f#", azStepsPerArcmin * 60.0f); return; }
    if (strcmp(body, "XGM") == 0)
    {
        Serial.print("ESP32,NO_RA,NO_DEC,NO_GPS,AUTO_AZ_ALT,NO_GYRO,NO_LCD,NO_FOC,NO_ENDSW#");
        return;
    }
    if (strcmp(body, "XGMS") == 0) { Serial.print("PA,1,1|PA,1,1|#"); return; }

    // Relative PA movement.  The official MAL/MAZ commands are silent.
    if (strncmp(body, "MAL", 3) == 0)
    {
        float arcmin;
        if (!parseFloatStrict(body + 3, arcmin)) { setFault("BAD_ALT_CMD"); return; }
        const double requestedSteps = static_cast<double>(arcmin) * altStepsPerArcmin;
        if (requestedSteps < INT32_MIN || requestedSteps > INT32_MAX)
        {
            setFault("ALT_RANGE");
            return;
        }
        const int32_t delta = static_cast<int32_t>(llround(requestedSteps));
        reportMoveResult(altitude.moveBy(delta), false);
        return;
    }
    if (strncmp(body, "MAZ", 3) == 0)
    {
        float arcmin;
        if (!parseFloatStrict(body + 3, arcmin)) { setFault("BAD_AZ_CMD"); return; }
        const double requestedSteps = static_cast<double>(arcmin) * azStepsPerArcmin;
        if (requestedSteps < INT32_MIN || requestedSteps > INT32_MAX)
        {
            setFault("AZ_RANGE");
            return;
        }
        const int32_t delta = static_cast<int32_t>(llround(requestedSteps));
        reportMoveResult(azimuth.moveBy(delta), false);
        return;
    }
    if (strncmp(body, "MXl", 3) == 0)
    {
        int32_t steps;
        if (!parseLongStrict(body + 3, steps))
        {
            setFault("BAD_ALT_CMD");
            Serial.print('0');
            return;
        }
        reportMoveResult(altitude.moveBy(steps), true);
        return;
    }
    if (strncmp(body, "MXz", 3) == 0)
    {
        int32_t steps;
        if (!parseLongStrict(body + 3, steps))
        {
            setFault("BAD_AZ_CMD");
            Serial.print('0');
            return;
        }
        reportMoveResult(azimuth.moveBy(steps), true);
        return;
    }

    // Home/zero and stop.
    if (strcmp(body, "hZ") == 0)
    {
        if (altitude.isMoving() || azimuth.isMoving()) { Serial.print('0'); return; }
        altitude.setCurrentPosition(0);
        azimuth.setCurrentPosition(0);
        markPositionDirty();
        persistPositions(true);
        Serial.print('1');
        return;
    }
    if (strcmp(body, "MAA") == 0 || strcmp(body, "MAAH") == 0)
    {
        const MoveResult azResult = azimuth.moveTo(0);
        const MoveResult altResult = altitude.moveTo(0);
        Serial.print((azResult == MoveResult::Accepted && altResult == MoveResult::Accepted) ? '1' : '0');
        return;
    }
    if (strcmp(body, "Q") == 0)
    {
        azimuth.stopNow();
        altitude.stopNow();
        markPositionDirty();
        persistPositions(true);
        return;
    }

    if (body[0] == 'P') { handlePaExtension(body); return; }

    // Accept harmless LX200 set operations so Ekos can synchronize time and
    // location without blocking.  They are intentionally not persisted.
    if (body[0] == 'S') { Serial.print('1'); return; }

    // Ignore unsupported RA/DEC/tracking/park commands.  This controller owns
    // only the polar-alignment base.
}

void serviceSerial()
{
    while (Serial.available() > 0)
    {
        const char incoming = static_cast<char>(Serial.read());
        // LX200/INDI performs its initial handshake with a raw ACK byte,
        // outside the normal colon/hash command framing.  "P" means polar.
        if (static_cast<uint8_t>(incoming) == 0x06)
        {
            receivingCommand = false;
            commandLength = 0;
            Serial.print('P');
            continue;
        }
        if (incoming == ':')
        {
            receivingCommand = true;
            commandLength = 0;
            commandBuffer[commandLength++] = incoming;
            continue;
        }
        if (!receivingCommand)
            continue;
        if (incoming == '#')
        {
            commandBuffer[commandLength] = '\0';
            receivingCommand = false;
            processCommand(commandBuffer);
            continue;
        }
        if (commandLength < sizeof(commandBuffer) - 1)
            commandBuffer[commandLength++] = incoming;
        else
        {
            receivingCommand = false;
            commandLength = 0;
            setFault("CMD_TOO_LONG");
        }
    }
}

void setup()
{
    Serial.begin(Config::SERIAL_BAUD);

    preferences.begin("b1autoalign", false);
    altStepsPerArcmin = preferences.getFloat("altCal", Config::DEFAULT_ALT_STEPS_PER_ARCMIN);
    azStepsPerArcmin = preferences.getFloat("azCal", Config::DEFAULT_AZ_STEPS_PER_ARCMIN);
    altMaxEnabled = preferences.getBool("altMaxEn", false);
    altMaxPosition = preferences.getLong("altMax", 0);

    const int32_t savedAlt = preferences.getLong("altPos", Config::DEFAULT_ALT_MIN);
    const int32_t savedAz = preferences.getLong("azPos", 0);
    altitude.begin(savedAlt);
    azimuth.begin(savedAz);
    altitude.setLimits(true, Config::DEFAULT_ALT_MIN, altMaxEnabled, altMaxPosition);
    azimuth.setLimits(false, 0, false, 0);
}

void loop()
{
    serviceSerial();
    const uint32_t now = micros();
    const bool altStepped = altitude.service(now);
    const bool azStepped = azimuth.service(now);
    if (altStepped || azStepped)
        markPositionDirty();
    persistPositions(false);
    delay(0);
}


