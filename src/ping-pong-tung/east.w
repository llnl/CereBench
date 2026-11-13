xp param tensor_size;
xp param num_msgs;

xp socket rx;
xp socket tx;

xp a[n=tensor_size];

m in [0, num_msgs) {
    i in [0, tensor_size)
        a[i] <- rx[];

    i in [0, tensor_size)
        tx[] <- a[i] + m + 1;
}
