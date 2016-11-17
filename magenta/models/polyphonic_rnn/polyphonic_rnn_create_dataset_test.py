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
"""Tests for drums_rnn_create_dataset."""

# internal imports

import tensorflow as tf
import magenta

from magenta.models.shared import events_rnn_model
from magenta.models.polyphonic_rnn import polyphonic_rnn_create_dataset
from magenta.models.polyphonic_rnn import polyphony_encoder_decoder
from magenta.pipelines import pipelines_common
from magenta.protobuf import music_pb2


FLAGS = tf.app.flags.FLAGS


class PolySeqPipelineTest(tf.test.TestCase):

  def setUp(self):
    self.config = events_rnn_model.EventSequenceRnnConfig(
        None,
        magenta.music.OneHotEventSequenceEncoderDecoder(
          polyphony_encoder_decoder.PolyphonyOneHotEncoding()),
        magenta.common.HParams())

  def testPolyRNNPipeline(self):
    note_sequence = magenta.common.testing_lib.parse_test_proto(
        music_pb2.NoteSequence,
        """
        time_signatures: {
          numerator: 4
          denominator: 4}
        tempos: {
          qpm: 120}""")
    magenta.music.testing_lib.add_track_to_sequence(
        note_sequence, 0,
        [(36, 100, 0.00, 2.0), (40, 55, 2.1, 5.0), (44, 80, 3.6, 5.0),
         (41, 45, 5.1, 8.0), (64, 100, 6.6, 10.0), (55, 120, 8.1, 11.0),
         (39, 110, 9.6, 9.7), (53, 99, 11.1, 14.1), (51, 40, 12.6, 13.0),
         (55, 100, 14.1, 15.0), (54, 90, 15.6, 17.0), (60, 100, 17.1, 18.0)])

    pipeline_inst = polyphonic_rnn_create_dataset.get_pipeline(
      steps_per_quarter=4,
      min_steps=80,  # 5 measures
      max_steps=1000,
      eval_ratio=0,
      config=self.config)
    result = pipeline_inst.transform(note_sequence)
    self.assertTrue(len(result['training_poly_tracks']) > 0)


if __name__ == '__main__':
  tf.test.main()
