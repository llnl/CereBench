xp param tensor_size;
xp param num_msgs;

xp socket tx;
xp socket rx;

xp a[n=tensor_size];

i in [0, tensor_size) a[i] <- i + 1;

m in [0, num_msgs) {
    i in [0, tensor_size)
        tx[] <- a[i];

    i in [0, tensor_size)
        a[i] <- rx[];
}
