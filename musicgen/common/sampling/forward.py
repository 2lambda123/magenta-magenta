import tensorflow as tf
import numpy as np
import copy

# TODO: 'temperature' parameter to control how random the sampling is?

def batchify_dict(dic, batch_size):
	return { name: np.tile(x, (batch_size, 1, 1)) for name,x in dic.iteritems() }

class ForwardSample(object):

	def __init__(self, model, checkpoint_dir, batch_size=1):
		self.model = model
		# how many sequences are going in parallel
		self.batch_size = batch_size

		# Construct a graph that takes placeholder inputs and produces the time slice Distribution
		self.input_placeholder = tf.placeholder(dtype=tf.float32, shape=[batch_size,None,self.model.timeslice_size], name = "inputs")
		self.condition_dict_placeholders = {
			name: tf.placeholder(dtype=tf.float32, shape=[batch_size,None]+shape) for name,shape in model.condition_shapes.iteritems()
		}
		self.rnn_state = model.initial_state(batch_size)
		self.final_state, self.rnn_outputs = model.run_rnn(self.rnn_state, self.input_placeholder)
		self.dist = model.get_step_dist(self.rnn_outputs, self.condition_dict_placeholders)
		self.sampled_timeslice = self.dist.sample()

		# Setup a session and restore saved variables
		self.sess = tf.Session()
		checkpoint_filename = tf.train.latest_checkpoint(checkpoint_dir)
		saver = tf.train.Saver()
		saver.restore(self.sess, checkpoint_filename)

		# Particle filtering stuff
		self.log_probabilities = np.zeros(self.batch_size)
		self.sample_placeholder = tf.placeholder(dtype = tf.int32, shape=[batch_size, self.model.timeslice_size], name = "samples")
		self.log_probability_node = self.dist.log_prob(self.sample_placeholder)

	"""
	Draw forward samples from a SequenceGenerativeModel for n_steps.
	initial_timeslices: a sequence of timeslices to use for 'priming' the model.
	condition_dicts: a sequence of input dictionaries that provide additional conditioning
	   information as sampling is happening. If 'initial_timeslices' is defined, then the
	   first len(initial_timeslices) of these correspond to the initial timeslices.
	returns: a list of list of timeslice samples from the model
	"""
	def sample(self, n_steps, initial_timeslices=None, condition_dicts=None):

		if condition_dicts is not None:
			# Copy, b/c we're going to mutate it
			condition_dicts = { k: v for k,v in condition_dicts.iteritems() }
			# Assert that we have enough
			n_initial_timeslices = 1 if (initial_timeslices is None) else len(initial_timeslices)
			assert(len(condition_dicts) == (n_initial_timeslices - 1) + n_steps)

		# Initialize the timeslice history and the input to the RNN
		timeslice_history = []
		rnn_input = None
		if initial_timeslices is not None:
			# Construct a list of input vecs (discarding initial condition dicts
			#   as we go)
			input_vecs = []
			for timeslice in initial_timeslices:
				if (condition_dicts is not None) and len(input_vecs) > 0:
					condition_dicts.pop(0)
				timeslice_history.append(timeslice)
				condition_dict = {} if (condition_dicts is None) else condition_dicts[0]
				input_vecs.append(self.model.next_rnn_input(timeslice_history, condition_dict))
			# Join them, creating a new 'time' dimension
			rnn_input = np.stack(input_vecs)
		else:
			# Just use the model's default initial time slice
			timeslice_history.append(self.model.default_initial_timeslice())
			condition_dict = {} if (condition_dicts is None) else condition_dicts[0]
			rnn_input = self.model.next_rnn_input(timeslice_history, condition_dict)
			# Create a singleton 'time' dimension
			rnn_input = rnn_input[np.newaxis]
		# Batchify the rnn input and each timeslice in the history
		rnn_input = np.tile(rnn_input, [self.batch_size, 1, 1])
		for i in range(len(timeslice_history)):
			timeslice_history[i] = np.tile(timeslice_history[i], [self.batch_size, 1, 1])


		if condition_dicts is not None:
			# Batchify the (remaining) condition dicts, too
			condition_dicts = [ batchify_dict(dic, self.batch_size) for dic in condition_dicts ]

		# Initialize state
		rnn_state = self.sess.run(self.rnn_state)

		# Iteratively draw sample, and convert the sample into the next input
		for i in range(n_steps):
			condition_dict = {} if (condition_dicts is None) else condition_dicts[i]
			rnn_state, sample = self.sample_step(rnn_state, rnn_input, condition_dict, i)
			while self.model.eval_factor_function(sample, condition_dict) == 0:
				print "hullo"
				rnn_state, sample = self.sample_step(rnn_state, rnn_input, condition_dict, i)
			timeslice_history.append(sample)
			rnn_input = self.model.next_rnn_input(timeslice_history, condition_dict)

		# Concatenate timeslices along time dimension to make one big block.
		# Then split along batch dimension, and then again along time dimension, so return value
		#    is a triply-nested list
		n_total = len(timeslice_history)
		batchTensor = np.concatenate(timeslice_history, 1)
		listOfSeqTensors = [seq[0] for seq in np.split(batchTensor, self.batch_size, axis=0)]
		return[[slic[0] for slic in np.split(seq, n_total, axis=0)] for seq in listOfSeqTensors]



	"""
	Generate for one time step
	Returns next rnn state as well as the sampled time slice
	"""
	def sample_step(self, rnn_state, rnn_input, condition_dict, step):
		# First, we run the graph to get the rnn outputs and next state
		feed_dict = { self.input_placeholder: rnn_input, self.rnn_state: rnn_state }
		next_state, outputs = self.sess.run([self.final_state, self.rnn_outputs], feed_dict)

		# Next, we slice out the last timeslice of the outputs--we only want to
		#    compute a distribution over that
		# (Can't do this in the graph b/c we don't know how long initial_timeslices will be up-front)
		seq_len = outputs.shape[1]
		if seq_len > 1:
			# slices out the last time entry but keeps the tensor 3D
			outputs = outputs[:, seq_len-1, np.newaxis, :]

		# Then, we feed this into the rest of the graph to sample from the
		#    timeslice distribution
		feed_dict = {self.condition_dict_placeholders[name]: condition_dict[name] for name in condition_dict}
		feed_dict[self.rnn_outputs] = outputs
		sample = self.sess.run(self.sampled_timeslice, feed_dict)

		for i in range(2):
			# calculate log probabilities here for each element of sample
			feed_dict[self.sample_placeholder] = sample 
			log_probabilities = self.sess.run(self.log_probability_node, feed_dict)
			log_probabilities = np.sum(-log_probabilities, axis = 1)
			#log_probabilities = -log_probabilities[:, step]
			normalized_log_probabilities = (self.log_probabilities+log_probabilities)/sum(self.log_probabilities + log_probabilities)
			#print normalized_log_probabilities
			
			new_sample = np.zeros(sample.shape)
			for i in range(self.batch_size):
				new_dist = np.random.multinomial(1, normalized_log_probabilities)
				new_sample[i] = np.matmul(new_dist.reshape(1, -1), sample)

			sample = new_sample
		
		feed_dict[self.sample_placeholder] = sample
		log_probabilities = self.sess.run(self.log_probability_node, feed_dict)
		log_probabilities = np.sum(-log_probabilities, axis = 1)
		self.log_probabilities += log_probabilities

		# Finally, we reshape the sample to be 3D again (the Distribution is over 2D [batch, depth]
		#    tensors--we need to reshape it to [batch, time, depth], where time=1)
		sample = sample[:,np.newaxis,:]

		return next_state, sample

		#REBUILD environmment



