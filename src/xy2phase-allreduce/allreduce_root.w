// SCALAR_ALLREDUCE_48BIT_PATCH
xp param W;
xp param H;
xp param B;
xp param SX;
xp param SY;
xp param WAIT_ALPHA;

socket x1;
socket y1;
socket x2a;
socket x2b;
socket y2a;
socket y2b;
socket bcast [[dir=out]];

sp value[n=B];
sp initial_value[n=B];
sp result[n=1];
sp scalar_result;
sp barrier_value;
sp sync_token;


xp done[n=1] = {0};
sp incoming;

xp x;
xp y;

xp coord[k=2];

xp x_rem;
xp x_group_start;
xp x_group_size;
xp x_group_id;
xp x_group_count;
xp x_local;

xp y_rem;
xp y_group_start;
xp y_group_size;
xp y_group_id;
xp y_group_count;
xp y_local;

xp debug_xphase[n=6];

// Hardware timer registers.
xp const timer_addr = 0x7b30;
xp const timer_control_addr = 0x7b34;

xp wait_left;
xp wait_count;
xp wait_sink[n=1];
xp sync_timing[n=4];

xp timerreg[3] address(timer_addr);
xp timercontrolreg[1] address(timer_control_addr);

// CG-compatible timing layout:
// reference, operation start, producer end,
// reduction end, AllReduce end.
// Plain AllReduce has no producer, so producer end equals start.
xp phase_timestamps[n=15];

xp timer_start[1];
xp timer_stop[1];

// Four 16-bit words occupy the same storage as two u32 values.
xp tsc_buffer[n=4];

{
    x <- coord[0];
    y <- coord[1];


    // Convert calibrated cycle delay to wait-loop iterations.
    wait_left <- WAIT_ALPHA * (W + H - x - y) + 4;
    wait_count <- 0;

    while (wait_left >= 9) {
        wait_left <- wait_left - 9;
        wait_count <- wait_count + 1;
    }


    done[0] <- 0;

    // Enable the free-running hardware timer once.
    timercontrolreg[0] <- 4;

    i in [0, 15) {
        phase_timestamps[i] <- 0;
    }

    timer_start[0] <- 0;
    timer_stop[0] <- 0;

    tsc_buffer[0] <- 0;
    tsc_buffer[1] <- 0;
    tsc_buffer[2] <- 0;
    tsc_buffer[3] <- 0;

    sync_timing[0] <- 0;
    sync_timing[1] <- 0;
    sync_timing[2] <- 0;
    sync_timing[3] <- 0;

    // --------------------------------------------------------
    // Precompute horizontal grouping.
    // --------------------------------------------------------

    x_rem <- W % SX;
    x_group_start <- 0;
    x_group_size <- SX;
    x_group_id <- 0;
    x_group_count <- 0;
    x_local <- x;

    if (x_rem != 0) {
        x_group_count <- (W / SX) + 1;

        if (x < x_rem) {
            x_group_size <- x_rem;
        } else {
            x_group_start <- x_rem;
            x_group_id <- 1;
            x_local <- x - x_rem;

            while (x_local >= SX) {
                x_local <- x_local - SX;
                x_group_start <- x_group_start + SX;
                x_group_id <- x_group_id + 1;
            }
        }
    } else {
        x_group_count <- W / SX;

        while (x_local >= SX) {
            x_local <- x_local - SX;
            x_group_start <- x_group_start + SX;
            x_group_id <- x_group_id + 1;
        }
    }

    debug_xphase[0] <- x;
    debug_xphase[1] <- y;
    debug_xphase[2] <- x_group_start;
    debug_xphase[3] <- x_group_size;
    debug_xphase[4] <- x_group_id;
    debug_xphase[5] <- x_local;

    // --------------------------------------------------------
    // Precompute vertical grouping.
    // --------------------------------------------------------

    y_rem <- H % SY;
    y_group_start <- 0;
    y_group_size <- SY;
    y_group_id <- 0;
    y_group_count <- 0;
    y_local <- y;

    if (y_rem != 0) {
        y_group_count <- (H / SY) + 1;

        if (y < y_rem) {
            y_group_size <- y_rem;
        } else {
            y_group_start <- y_rem;
            y_group_id <- 1;
            y_local <- y - y_rem;

            while (y_local >= SY) {
                y_local <- y_local - SY;
                y_group_start <- y_group_start + SY;
                y_group_id <- y_group_id + 1;
            }
        }
    } else {
        y_group_count <- H / SY;

        while (y_local >= SY) {
            y_local <- y_local - SY;
            y_group_start <- y_group_start + SY;
            y_group_id <- y_group_id + 1;
        }
    }

    // Preserve the original input for the measured run.
    i in [0, B) {
        initial_value[i] <- value[i];
    }
    // ========================================================
    // PASS 0: WARMUP ALLREDUCE
    // ========================================================

    // Horizontal phase 1.
    if (x_group_size > 1) {
        i in [0, B) {
            if (x_local != x_group_size - 1) {
                incoming <- x1[];
                value[i] <- value[i] + incoming;
            }

            if (x_local != 0) {
                x1[] <- value[i];
            }
        }
    }

    // Horizontal phase 2.
    if (x_local == 0) {
        if (x_group_count > 1) {
            i in [0, B) {
                if (x_group_id != x_group_count - 1) {
                    if ((x_group_id & 1) == 0) {
                        incoming <- x2a[];
                    } else {
                        incoming <- x2b[];
                    }

                    value[i] <- value[i] + incoming;
                }

                if (x_group_id != 0) {
                    if ((x_group_id & 1) == 1) {
                        x2a[] <- value[i];
                    } else {
                        x2b[] <- value[i];
                    }
                }
            }
        }
    }

    // Vertical reduction on column zero.
    if (x == 0) {
        // Vertical phase 1.
        if (y_group_size > 1) {
            i in [0, B) {
                if (y_local != y_group_size - 1) {
                    incoming <- y1[];
                    value[i] <- value[i] + incoming;
                }

                if (y_local != 0) {
                    y1[] <- value[i];
                }
            }
        }

        // Vertical phase 2.
        if (y_local == 0) {
            if (y_group_count > 1) {
                i in [0, B) {
                    if (y_group_id != y_group_count - 1) {
                        if ((y_group_id & 1) == 0) {
                            incoming <- y2a[];
                        } else {
                            incoming <- y2b[];
                        }

                        value[i] <- value[i] + incoming;
                    }

                    if (y_group_id != 0) {
                        if ((y_group_id & 1) == 1) {
                            y2a[] <- value[i];
                        } else {
                            y2b[] <- value[i];
                        }
                    }
                }
            }
        }
    }

    // Fold the reduced vector to one scalar.
    scalar_result <- 0;

    i in [0, B) {
        scalar_result <- scalar_result + value[i];
    }

    result[0] <- scalar_result;
    bcast[] <- scalar_result;

    // Restore identical input outside the measured region.
    i in [0, B) {
        value[i] <- initial_value[i];
    }

    // ========================================================
// POST-WARMUP BARRIER
// ========================================================

// Scalar X-Y reduction to root.
barrier_value <- 1;

if (x_group_size > 1) {
    if (x_local != x_group_size - 1) {
        incoming <- x1[];
        barrier_value <- barrier_value + incoming;
    }

    if (x_local != 0) {
        x1[] <- barrier_value;
    }
}

if (x_local == 0) {
    if (x_group_count > 1) {
        if (x_group_id != x_group_count - 1) {
            if ((x_group_id & 1) == 0) {
                incoming <- x2a[];
            } else {
                incoming <- x2b[];
            }

            barrier_value <- barrier_value + incoming;
        }

        if (x_group_id != 0) {
            if ((x_group_id & 1) == 1) {
                x2a[] <- barrier_value;
            } else {
                x2b[] <- barrier_value;
            }
        }
    }
}

if (x == 0) {
    if (y_group_size > 1) {
        if (y_local != y_group_size - 1) {
            incoming <- y1[];
            barrier_value <- barrier_value + incoming;
        }

        if (y_local != 0) {
            y1[] <- barrier_value;
        }
    }

    if (y_local == 0) {
        if (y_group_count > 1) {
            if (y_group_id != y_group_count - 1) {
                if ((y_group_id & 1) == 0) {
                    incoming <- y2a[];
                } else {
                    incoming <- y2b[];
                }

                barrier_value <- barrier_value + incoming;
            }

            if (y_group_id != 0) {
                if ((y_group_id & 1) == 1) {
                    y2a[] <- barrier_value;
                } else {
                    y2b[] <- barrier_value;
                }
            }
        }
    }
}
// Root establishes the reference event and broadcasts a trigger.
phase_timestamps[0] <- timerreg[0];
phase_timestamps[1] <- timerreg[1];
phase_timestamps[2] <- timerreg[2];

sync_timing[0] <- phase_timestamps[0];

sync_token <- 1;
bcast[] <- sync_token;

    // Apply the same calibrated synchronization delay.
    wait_left <- wait_count;

    while (wait_left > 0) {
        wait_sink[0] <- wait_left;
        wait_left <- wait_left - 1;
    }

    // ========================================================
    // PASS 1: MEASURED ALLREDUCE
    // ========================================================

    phase_timestamps[3] <- timerreg[0];
    phase_timestamps[4] <- timerreg[1];
    phase_timestamps[5] <- timerreg[2];

    // There is no producer stage in plain AllReduce.
    phase_timestamps[6] <- phase_timestamps[3];
    phase_timestamps[7] <- phase_timestamps[4];
    phase_timestamps[8] <- phase_timestamps[5];

    timer_start[0] <- phase_timestamps[3];

    // Horizontal phase 1.
    if (x_group_size > 1) {
        i in [0, B) {
            if (x_local != x_group_size - 1) {
                incoming <- x1[];
                value[i] <- value[i] + incoming;
            }

            if (x_local != 0) {
                x1[] <- value[i];
            }
        }
    }

    // Horizontal phase 2.
    if (x_local == 0) {
        if (x_group_count > 1) {
            i in [0, B) {
                if (x_group_id != x_group_count - 1) {
                    if ((x_group_id & 1) == 0) {
                        incoming <- x2a[];
                    } else {
                        incoming <- x2b[];
                    }

                    value[i] <- value[i] + incoming;
                }

                if (x_group_id != 0) {
                    if ((x_group_id & 1) == 1) {
                        x2a[] <- value[i];
                    } else {
                        x2b[] <- value[i];
                    }
                }
            }
        }
    }

    // Vertical reduction on column zero.
    if (x == 0) {
        // Vertical phase 1.
        if (y_group_size > 1) {
            i in [0, B) {
                if (y_local != y_group_size - 1) {
                    incoming <- y1[];
                    value[i] <- value[i] + incoming;
                }

                if (y_local != 0) {
                    y1[] <- value[i];
                }
            }
        }

        // Vertical phase 2.
        if (y_local == 0) {
            if (y_group_count > 1) {
                i in [0, B) {
                    if (y_group_id != y_group_count - 1) {
                        if ((y_group_id & 1) == 0) {
                            incoming <- y2a[];
                        } else {
                            incoming <- y2b[];
                        }

                        value[i] <- value[i] + incoming;
                    }

                    if (y_group_id != 0) {
                        if ((y_group_id & 1) == 1) {
                            y2a[] <- value[i];
                        } else {
                            y2b[] <- value[i];
                        }
                    }
                }
            }
        }
    }

    // Reduction complete, immediately before broadcast.
    phase_timestamps[9] <- timerreg[0];
    phase_timestamps[10] <- timerreg[1];
    phase_timestamps[11] <- timerreg[2];

    // Fold the reduced vector, then broadcast one scalar.
    scalar_result <- 0;

    i in [0, B) {
        scalar_result <- scalar_result + value[i];
    }

    result[0] <- scalar_result;
    bcast[] <- scalar_result;

    phase_timestamps[12] <- timerreg[0];
    phase_timestamps[13] <- timerreg[1];
    phase_timestamps[14] <- timerreg[2];

    // Preserve the legacy low-word fields for compatibility.
    timer_stop[0] <- phase_timestamps[12];

tsc_buffer[0] <- timer_stop[0] - timer_start[0];
    tsc_buffer[1] <- 0;
    tsc_buffer[2] <- 0;
    tsc_buffer[3] <- 0;

    sync_timing[1] <- timer_start[0];
    sync_timing[2] <- timer_stop[0];
    sync_timing[3] <- timer_start[0] - timer_stop[0];
    done[0] <- 1;
}
