import sys
import numpy as np

# matches west.w's Makefile invocation: ref.py $@ tensor_size DIST NUM_MSGS
# DIST isn't used by this design (west.w/east.w declare no such param)
outfile = sys.argv[1]
tensor_size = int(sys.argv[2])
num_msgs = int(sys.argv[4])

# west.w initialises a[i] = i + 1 itself; there is no input file to read
a = np.arange(1, tensor_size + 1, dtype=np.int16)

increment = num_msgs * (num_msgs + 1) // 2
out = a + increment

out.astype(np.int16).tofile(outfile)
