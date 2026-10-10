package io.papermc.paper.threadedregions.scheduler;
public interface ScheduledTask {
    enum CancelledState { CANCELLED_BY_CALLER }
    CancelledState cancel();
}
