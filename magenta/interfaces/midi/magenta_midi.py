# Copyright 2016 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""A MIDI interface to the sequence generators.

Captures monophonic input MIDI sequences and plays back responses from the
sequence generator.
"""

import ast
import functools
from sys import stdout
import threading
import time

# internal imports
import mido
import tensorflow as tf
import magenta

from magenta.interfaces.midi import midi_hub
from magenta.interfaces.midi import midi_interaction
from magenta.models.attention_rnn import attention_rnn_generator
from magenta.models.basic_rnn import basic_rnn_generator
from magenta.models.lookback_rnn import lookback_rnn_generator

FLAGS = tf.app.flags.FLAGS

tf.app.flags.DEFINE_bool(
    'list',
    False,
    'Only list available MIDI ports.')
tf.app.flags.DEFINE_string(
    'input_port',
    None,
    'The name of the input MIDI port.')
tf.app.flags.DEFINE_string(
    'output_port',
    None,
    'The name of the output MIDI port.')
tf.app.flags.DEFINE_integer(
    'phase_bars',
    None,
    'The number of bars of duration to use for the call and response phases. '
    'If none, `phase_control_number` must be specified.')
tf.app.flags.DEFINE_integer(
    'phase_control_number',
    None,
    'The control change number to use as a signal to end the call phase. If '
    'None, `phase_bars` must be specified.')
# TODO(adarob): Make the qpm adjustable by a control change signal.
tf.app.flags.DEFINE_integer(
    'qpm',
    90,
    'The quarters per minute to use for the metronome and generated sequence.')
tf.app.flags.DEFINE_string(
    'bundle_file',
    None,
    'The location of the bundle file to use.')

# A map from a string generator name to its factory class.
_GENERATOR_FACTORY_MAP = {
    'attention_rnn': attention_rnn_generator,
    'basic_rnn': basic_rnn_generator,
    'lookback_rnn': lookback_rnn_generator,
}


def main(unused_argv):
  if FLAGS.list:
    print "Input ports: '" + "', '".join(mido.get_input_names()) + "'"
    print "Output ports: '" + "', '".join(mido.get_output_names()) + "'"
    return

  if FLAGS.input_port is None or FLAGS.output_port is None:
    print '--inport_port and --output_port must be specified.'
    return

  if FLAGS.bundle_file is None:
    print '--bundle_file must be specified.'
    return

  if (FLAGS.phase_control_number, FLAGS.phase_bars).count(None) != 1:
    print('Exactly one of --phase_control_number or --phase_bars should be '
          'specified.')
    return

  try:
    bundle = magenta.music.sequence_generator_bundle.read_bundle_file(
        FLAGS.bundle_file)
  except magenta.music.sequence_generator_bundle.GeneratorBundleParseException:
    print 'Failed to prase bundle file: %s' % FLAGS.bundle_file
    return

  generator_id = bundle.generator_details.id
  if generator_id not in _GENERATOR_FACTORY_MAP:
    print "Unrecognized SequenceGenerator ID '%s' in bundle file: %s" % (
        generator_id, FLAGS.bundle_file)
    return
  generator = _GENERATOR_FACTORY_MAP[generator_id].create_generator(
      checkpoint=None, bundle=bundle)
  generator.initialize()
  print "Loaded '%s' generator bundle from file '%s'." %(
      bundle.generator_details.id, FLAGS.bundle_file)

  hub = midi_hub.MidiHub(FLAGS.input_port, FLAGS.output_port,
                         midi_hub.TextureType.MONOPHONIC)

  end_call_signal = (None if FLAGS.phase_control_number is None else
                     midi_hub.MidiSignal(control=FLAGS.phase_control_number,
                                         value=0))
  interaction = midi_interaction.CallAndResponseMidiInteraction(
      hub,
      FLAGS.qpm,
      generator,
      phase_bars=FLAGS.phase_bars,
      end_call_signal=end_call_signal)

  print ''
  print 'Instructions:'
  print 'Play when you hear the metronome ticking.'
  if FLAGS.phase_bars is not None:
    print 'After %d bars, Magenta will play its response.' % FLAGS.phase_bars
    print ('Once the response completes, the metronome will tick and you can '
           'play again.')
  else:
    print ('When you want to end the call phase, signal control number %d '
           'with value 0' % FLAGS.phase_control_number)
    print 'At the end of the bar, Magenta will play its response.'
    print ('Once the response completes, the metronome will tick and you can '
           'play again.')
  print ''
  print 'To end the interaction, press CTRL-C.'

  interaction.start()
  try:
    while True:
      time.sleep(1)
  except KeyboardInterrupt:
    interaction.stop()

  print 'Interaction stopped.'


def console_entry_point():
  tf.app.run(main)


if __name__ == '__main__':
  console_entry_point()
