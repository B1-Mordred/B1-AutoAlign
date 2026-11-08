#include <assert.h>
#include <limits.h>

#include "MotionAxis.h"

static StepDirAxis makeAxis(uint32_t timeoutMs = 1000)
{
    return StepDirAxis("TEST", 1, 2, 3, false, true, 800.0f, 500.0f, 40.0f, 3, timeoutMs);
}

static void testLimitsAndOverflow()
{
    auto axis = makeAxis();
    axis.begin(50);
    axis.setLimits(true, 0, true, 100);
    int32_t target = 0;
    assert(axis.calculateRelativeTarget(-51, target) == MoveResult::MinLimit);
    assert(axis.calculateRelativeTarget(51, target) == MoveResult::MaxLimit);
    assert(axis.calculateRelativeTarget(50, target) == MoveResult::Accepted);
    assert(target == 100);

    axis.setCurrentPosition(INT32_MAX);
    axis.setLimits(false, 0, false, 0);
    assert(axis.calculateRelativeTarget(1, target) == MoveResult::Range);
}

static void testHoldPolicies()
{
    auto axis = makeAxis();
    axis.begin(0);
    axis.setLimits(true, 0, true, 10);
    axis.setHoldPolicy(HoldMode::Always, 50);
    assert(axis.moveBy(1, 0, 0) == MoveResult::Accepted);
    assert(axis.driverIsEnabled());
    assert(axis.service(30000, 1) == ServiceResult::Completed);
    assert(axis.driverIsEnabled());

    fakeMillis = 2;
    axis.setHoldPolicy(HoldMode::Release, 50);
    assert(!axis.driverIsEnabled());

    axis.setHoldPolicy(HoldMode::Timed, 50);
    assert(axis.moveBy(1, 30000, 10) == MoveResult::Accepted);
    assert(axis.service(60000, 11) == ServiceResult::Completed);
    assert(axis.driverIsEnabled());
    assert(axis.service(60000, 60) == ServiceResult::Idle);
    assert(axis.driverIsEnabled());
    assert(axis.service(60000, 61) == ServiceResult::Idle);
    assert(!axis.driverIsEnabled());
}

static void testStopKeepsLoadHeld()
{
    auto axis = makeAxis();
    axis.begin(0);
    axis.setHoldPolicy(HoldMode::Always, 0);
    assert(axis.moveBy(10, 0, 0) == MoveResult::Accepted);
    assert(axis.service(30000, 1) == ServiceResult::Stepped);
    axis.stopNow(2);
    assert(!axis.isMoving());
    assert(axis.driverIsEnabled());
    assert(axis.position() == 1);
}

static void testRuntimeDirectionInversion()
{
    auto axis = makeAxis();
    axis.begin(0);
    assert(!axis.directionIsInverted());
    assert(axis.moveBy(1, 0, 0) == MoveResult::Accepted);
    assert(axis.service(30000, 1) == ServiceResult::Completed);
    assert(fakePinLevels[2]);

    axis.setCurrentPosition(0);
    axis.setDirectionInverted(true);
    assert(axis.directionIsInverted());
    assert(axis.moveBy(1, 30000, 2) == MoveResult::Accepted);
    assert(axis.service(60000, 3) == ServiceResult::Completed);
    assert(!fakePinLevels[2]);
}

static void testTimeoutAcrossMillisWrap()
{
    auto axis = makeAxis(100);
    axis.begin(0);
    axis.setHoldPolicy(HoldMode::Always, 0);
    const uint32_t start = UINT32_MAX - 50U;
    assert(axis.moveBy(10, 0, start) == MoveResult::Accepted);
    assert(axis.service(1000, 60) == ServiceResult::TimedOut);
    assert(!axis.isMoving());
    assert(axis.driverIsEnabled());
}

int main()
{
    testLimitsAndOverflow();
    testHoldPolicies();
    testStopKeepsLoadHeld();
    testRuntimeDirectionInversion();
    testTimeoutAcrossMillisWrap();
    return 0;
}
