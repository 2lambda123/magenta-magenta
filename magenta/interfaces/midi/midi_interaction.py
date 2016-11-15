"""A module for implementing interaction between MIDI and SequenceGenerators."""

import abc
import threading
import time

# internal imports
import tensorflow as tf

from magenta.protobuf import generator_pb2
from magenta.protobuf import music_pb2


class MidiInteractionException(Exception):
  """Base class for exceptions in this module."""
  pass


# TODO(adarob): Move to sequence_utils.
def merge_sequence_notes(sequence_1, sequence_2):
  """Returns a new NoteSequence combining the notes from both inputs.

  All fields aside from `notes` and `total_time` are copied from the first
  input.

  Args:
    sequence_1: A NoteSequence to merge. All fields aside from `notes` and
        `total_time` are copied directly from this sequence in the merged
        sequence.
    sequence_2: A NoteSequence to merge.

  Returns:
    A new NoteSequence combining the notes from the input sequences.
  """
  merged_sequence = music_pb2.NoteSequence()
  merged_sequence.CopyFrom(sequence_1)
  merged_sequence.notes.extend(sequence_2.notes)
  merged_sequence.total_time = max(sequence_1.total_time, sequence_2.total_time)
  return merged_sequence


# TODO(adarob): Move to sequence_utils.
def filter_instrument(sequence, instrument, from_time=0):
  """Returns a new NoteSequence with notes from the given instrument removed.

  Only notes that start on or after `from_time` will be completely removed.
  Those that start before and end after `from_time` will be truncated to end
  at `from_time`.

  Args:
    sequence: The NoteSequence to created the filtered sequence from.
    instrument: The instrument number to remove notes of.
    from_time: The time on or after which to remove or truncate notes.

  Returns:
    A new NoteSequence with notes from the given instrument removed or truncated
    after `from_time`.
  """
  filtered_sequence = music_pb2.NoteSequence()
  filtered_sequence.CopyFrom(sequence)
  del filtered_sequence.notes[:]
  for note in sequence.notes:
    if note.instrument == instrument:
      if note.start_time >= from_time:
        continue
      if note.end_time >= from_time:
        note.end_time = from_time
    filtered_sequence.notes.add().CopyFrom(note)
  return filtered_sequence


def temperature_from_control_value(
    val, min_temp=0.1, mid_temp=1.0, max_temp=2.0):
  """Computes the temperature from an 8-bit MIDI control value.

  Linearly interpolates between the middle temperature and an endpoint.

  Args:
    val: The MIDI control value in the range [0, 127] or None. If None, returns
        `mid_temp`.
    min_temp: The minimum temperature, which will be returned when `val` is 0.
    mid_temp: The middle temperature, which will be returned when `val` is 63
       or 64.
    max_temp: The maximum temperature, which will be returned when `val` is 127.

  Returns:
    A float temperature value based on the 8-bit MIDI control value.
  """
  if val is None:
    return mid_temp
  if val > 64:
    return mid_temp + (val - 64) * (max_temp - mid_temp) / 63
  elif val < 63:
    return min_temp + val * (mid_temp - min_temp) / 63
  else:
    return mid_temp


class MidiInteraction(threading.Thread):
  """Base class for handling interaction between MIDI and SequenceGenerator.

  Child classes will provided the "main loop" of an interactive session between
  a MidiHub used for MIDI I/O and sequences generated by a SequenceGenerator in
  their `run` methods.

  Should be started by calling `start` to launch in a separate thread.

  Args:
    midi_hub: The MidiHub to use for MIDI I/O.
    qpm: The quarters per minute to use for this interaction.
  """
  _metaclass__ = abc.ABCMeta

  def __init__(self, midi_hub, qpm):
    self._midi_hub = midi_hub
    self._qpm = qpm
    # A signal to tell the main loop when to stop.
    self._stop_signal = threading.Event()
    super(MidiInteraction, self).__init__()

  @abc.abstractmethod
  def run(self):
    """The main loop for the interaction.

    Must exit shortly after `self._stop_signal` is set.
    """
    pass

  def stop(self):
    """Stops the main loop, and blocks until the interaction is stopped."""
    self._stop_signal.set()
    self.join()


class CallAndResponseMidiInteraction(MidiInteraction):
  """Implementation of a MidiInteraction for real-time "call and response".

  Alternates between receiving input from the MidiHub ("call") and playing
  generated sequences ("response"). During the call stage, the input is captured
  and used to generate the response, which is then played back during the
  response stage.

  Args:
    midi_hub: The MidiHub to use for MIDI I/O.
    qpm: The quarters per minute to use for this interaction.
    sequence_generator: The SequenceGenerator to use to generate the responses
        in this interaction.
    steps_per_quarter: The number of steps per quarter note.
    steps_per_bar: The number of steps in each bar/measure.
    phrase_bars: The optional number of bars in each phrase. `end_call_signal`
        must be provided if None.
    start_call_signal: The control change number to use as a signal to start the
       call phrase. If None, call will start immediately after response.
    end_call_signal: The optional midi_hub.MidiSignal to use as a signal to stop
        the call phrase at the end of the current bar. `phrase_bars` must be
        provided if None.
  """
  _INITIAL_PREDICTAHEAD_STEPS = 4
  _MIN_PREDICTAHEAD_STEPS = 1

  def __init__(self,
               midi_hub,
               qpm,
               sequence_generator,
               steps_per_quarter=4,
               steps_per_bar=16,
               phrase_bars=None,
               start_call_signal=None,
               end_call_signal=None,
               temperature_control_number=None):
    super(CallAndResponseMidiInteraction, self).__init__(midi_hub, qpm)
    self._sequence_generator = sequence_generator
    self._steps_per_bar = steps_per_bar
    self._steps_per_quarter = steps_per_quarter
    self._phrase_bars = phrase_bars
    self._start_call_signal = start_call_signal
    self._end_call_signal = end_call_signal
    self._temperature_control_number = temperature_control_number

  def run(self):
    """The main loop for a real-time call and response interaction."""

    # We measure time in units of steps.
    seconds_per_step = 60.0 / (self._qpm * self._steps_per_quarter)
    # Start time in steps from the epoch.
    start_steps = (time.time() + 1.0) // seconds_per_step

    # The number of steps before call stage ends to start generation of response
    # Will be automatically adjusted to be as small as possible while avoiding
    # late response starts.
    predictahead_steps = self._INITIAL_PREDICTAHEAD_STEPS

    # Call stage start in steps from the epoch.
    call_start_steps = start_steps

    # The softmax temperature to use during generation.
    temperature = temperature_from_control_value(
        self._midi_hub.control_value(self._temperature_control_number))

    while not self._stop_signal.is_set():
      if self._start_call_signal is not None:
        # Wait for start signal.
        self._midi_hub.wait_for_event(self._start_call_signal)
        # Check to see if a stop has been requested.
        if self._stop_signal.is_set():
          break

      # Call stage.

      # Start the metronome at the beginning of the call stage.
      self._midi_hub.start_metronome(
          self._qpm, call_start_steps * seconds_per_step)

      # Start a captor at the beginning of the call stage.
      captor = self._midi_hub.start_capture(
          self._qpm, call_start_steps * seconds_per_step)

      if self._phrase_bars is not None:
        # The duration of the call stage in steps.
        call_steps = self._phrase_bars * self._steps_per_bar
      else:
        # Wait for end signal.
        self._midi_hub.wait_for_event(self._end_call_signal)
        # The duration of the call stage in steps.
        # We end the call stage at the end of the next bar that is at least
        # `predicathead_steps` in the future.
        call_steps = time.time() // seconds_per_step - call_start_steps
        remaining_call_steps = -call_steps % self._steps_per_bar
        if remaining_call_steps < predictahead_steps:
          remaining_call_steps += self._steps_per_bar
        call_steps += remaining_call_steps

      # Set the metronome to stop at the appropriate time.
      self._midi_hub.stop_metronome(
          (call_steps + call_start_steps) * seconds_per_step,
          block=False)

      # Stop the captor at the appropriate time.
      capture_steps = call_steps - predictahead_steps
      captor.stop(stop_time=(
          (capture_steps + call_start_steps) * seconds_per_step))
      captured_sequence = captor.captured_sequence()

      # Check to see if a stop has been requested during capture.
      if self._stop_signal.is_set():
        break

      # Generate sequence.
      response_start_steps = call_steps + call_start_steps
      response_end_steps = 2 * call_steps + call_start_steps

      generator_options = generator_pb2.GeneratorOptions()
      generator_options.generate_sections.add(
          start_time=response_start_steps * seconds_per_step,
          end_time=response_end_steps * seconds_per_step)

      # Check for updated temperature.
      new_temperature = temperature_from_control_value(
          self._midi_hub.control_value(self._temperature_control_number))
      if new_temperature is not None:
        if temperature != new_temperature:
          tf.logging.info('New temperature value: %d', new_temperature)
          temperature = new_temperature
        generator_options.args['temperature'].float_value = temperature

      # Generate response.
      response_sequence = self._sequence_generator.generate(
          captured_sequence, generator_options)

      # Check to see if a stop has been requested during generation.
      if self._stop_signal.is_set():
        break

      # Response stage.
      # Start response playback.
      self._midi_hub.start_playback(response_sequence)

      # Compute remaining time after generation before the response stage
      # starts, updating `predictahead_steps` appropriately.
      remaining_time = response_start_steps * seconds_per_step - time.time()
      if remaining_time > (predictahead_steps * seconds_per_step):
        predictahead_steps = max(self._MIN_PREDICTAHEAD_SEPS,
                                 response_start_steps - 1)
        tf.logging.info('Generator is ahead by %.3f seconds. '
                        'Decreasing `predictahead_steps` to %d.',
                        remaining_time, predictahead_steps)
      elif remaining_time < 0:
        predictahead_steps += 1
        tf.logging.warn('Generator is lagging by %.3f seconds. '
                        'Increasing `predictahead_steps` to %d.',
                        -remaining_time, predictahead_steps)

      call_start_steps = response_end_steps

  def stop(self):
    if self._start_call_signal is not None:
      self._midi_hub.wake_signal_waiters(self._start_call_signal)
    if self._end_call_signal is not None:
      self._midi_hub.wake_signal_waiters(self._end_call_signal)
    super(CallAndResponseMidiInteraction, self).stop()


class ExternalClockCallAndResponse(midi_interaction.MidiInteraction):
  """Implementation of a MidiInteraction which follows external sync timing.
  Alternates between receiving input from the MidiHub ("call") and playing
  generated sequences ("response"). During the call stage, the input is captured
  and used to generate the response, which is then played back during the
  response stage. The timing and length of the call and response stages are set
  by external MIDI signals.
  Args:
    midi_hub_io: The MidiHub to use for MIDI I/O.
    qpm: The quarters per minute to use for this interaction.
    sequence_generator: The SequenceGenerator to use to generate the responses
        in this interaction.
    quarters_per_bar: The number of quarter notes in each bar/measure.
    phrase_bars: The optional number of bars in each phrase. `end_call_signal`
        must be provided if None.
    start_call_signal: The control change number to use as a signal a new bar.
    start_call_signal: The control change number to use as a signal to start the
       call phrase.
    end_call_signal: The optional midi_hub.MidiSignal to use as a signal to stop
        the call phrase at the end of the current bar. `phrase_bars` must be
        provided if None.
  """
  def __init__(self,
               midi_hub,
               qpm,
               sequence_generator,
               clock_signal=None,
               end_call_signal=None,
               allow_overlap=False):
    super(ExternalClockCallAndResponse, self).__init__(midi_hub, qpm)
    self._clock_signal = clock_signal
    self._end_call_signal = end_call_signal
    self._allow_overlap = allow_overlap

    # Event for signalling when to end a call.
    self._end_call = threading.Event()

  def _end_call_callback(unused_captured_seq):
    self._end_call.set()

  def run(self):
    """The main loop for a real-time call and response interaction."""

    seconds_per_bar = 4 * 60.0 / self._qpm

    captor = self._midi_hub.start_capture(self._qpm, 0)

    # Set callback for end call signal.
    captor.register_callback(self._end_call_callback,
                             signal=self._end_call_signal)

    # Keep track of the end of the previous tick time.
    last_tick_time = 0

    for captured_seq in captor.iterate(self._clock_signal):
      if self._stop_signal.is_set():
        break

      tick_time = captured_sequence.total_time
      last_end_time = (max(note.end_time for note in captured_notes.notes)
                       if captured_notes.notes else None)
      if not captured_sequence.notes:
        # Reset captured sequence since we are still idling.
        tf.logging.info('Idle...')
        captor.start_time = tick_time
      elif last_end_time <= last_tick_time or self._end_call.is_set():
        # Create response and start playback.
        tf.logging.info('Responding...')

        # Compute duration of response.
        num_bars = (self._midi_hub.control_number(self._duration_control_number)
                    if self._duration_control_number is not None else None)
        if num_bars is not None and num_bars > 0:
          response_duration = num_bars * seconds_per_bar
        else:
          # Use capture duration.
          response_duration = tick_time - captor.start_time

        # Generate sequence options.
        response_start_time = tick_time
        response_end_time = response_start_time + response_duration

        generator_options = magenta.protobuf.generator_pb2.GeneratorOptions()
        generator_options.input_sections.add(
            start_time = captor.start_time,
            end_time = tick_time)
        generator_options.generate_sections.add(
            start_time=response_start_time,
            end_time=response_end_time)

        # Generate response.
        response_sequence = self._sequence_generator.generate(
            captured_sequence, generator_options)

        # Start response playback. Specify the start_time to avoid stripping
        # initial events due to generation lag.
        self._midi_hub.start_playback(response_sequence,
                                      start_time=response_start_time)

        # Do not capture anything until the end of playback.
        if not self._allow_overlap:
          captor.start_time = response_end_time

        # Clear end signal.
        self._end_call.clear()
      else:
        # Continue listening.
        tf.logging.info('Listening...')

      last_tick_time = tick_time

    captor.stop()
