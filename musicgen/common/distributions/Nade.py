"""The NADE distribution class."""

import tensorflow as tf

class NADE:
  """NADE distribution. """
  
  def __init__(self,a,b,W,V,dtype=tf.float32):
      """Construct Bernoulli distributions."""
      self.a,self.b,self.W,self.V,self.dtype=a,b,W,V,dtype
      
  def log_prob(self,targets):
    # assumes that targets is flattened
    # outputs a vector of (log)probability - one (log)probability for each timeslice entry
    ct = 0
    offset = tf.constant(10**(-14), dtype=tf.float32,name='offset', verify_shape=False)
    log_probability = 0
    with tf.variable_scope("NADE_step"):
      temp_a = a
      while True:
        hi = tf.sigmoid(temp_a)
        p_vi = tf.sigmoid(tf.slice(b,begin = (0, ct), size = (-1, 1)) + tf.matmul(hi, tf.slice(V, begin = (0, ct), size = (-1, 1))) )
        vi = tf.slice(targets_flat, begin = (0, ct), size = (-1, 1))
        temp_a = temp_a + tf.matmul(vi , tf.slice(W, begin = (ct, 0), size = (1,-1)) )
        log_prob = tf.multiply(vi,tf.log(p_vi + offset)) + tf.multiply((1-vi),tf.log((1-p_vi) + offset))  
        log_probability = log_probability + log_prob
        ct += 1
        if  ct >= timeslice_size:
          break
    print('log_probability: check shape!!', log_probability)
		return(log_probability)
    # Check that we can do the following operations on log_probability (these operations will be done in the file models/sequenceGenerativeModel.py)
    #log_prob= tf.reduce_sum(log_prob, 1)
		#num_time_slices = tf.to_float(tf.reduce_sum(lengths))
		#log_prob = tf.reduce_sum(mask_flat * log_prob) / num_time_slices
    
    # is it equivalent to doing loss = -tf.reduce_mean((tf.squeeze(log_probability,axis=1)))??
