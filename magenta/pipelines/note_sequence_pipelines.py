# Copyright 2017 Google Inc. All Rights Reserved.
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
"""NoteSequence processing pipelines."""

import copy

# internal imports
import tensorflow as tf

from magenta.music import constants
from magenta.music import sequences_lib
from magenta.pipelines import pipeline
from magenta.pipelines import statistics
from magenta.protobuf import music_pb2

# Shortcut to chord symbol text annotation type.
CHORD_SYMBOL = music_pb2.NoteSequence.TextAnnotation.CHORD_SYMBOL


class NoteSequencePipeline(pipeline.Pipeline):
  """Superclass for pipelines that input and output NoteSequences."""

  def __init__(self, name=None):
    super(NoteSequencePipeline, self).__init__(
        input_type=music_pb2.NoteSequence,
        output_type=music_pb2.NoteSequence,
        name=name)


class Splitter(NoteSequencePipeline):
  """A Pipeline that splits NoteSequences at regular intervals."""

  def __init__(self, hop_size_seconds, name=None):
    super(Splitter, self).__init__(name=name)
    self._hop_size_seconds = hop_size_seconds

  def transform(self, note_sequence):
    return sequences_lib.split_note_sequence(
        note_sequence, self._hop_size_seconds)


class TimeChangeSplitter(NoteSequencePipeline):
  """A Pipeline that splits NoteSequences on time signature & tempo changes."""

  def transform(self, note_sequence):
    return sequences_lib.split_note_sequence_on_time_changes(note_sequence)


class Quantizer(NoteSequencePipeline):
  """A Pipeline that quantizes NoteSequence data."""

  def __init__(self, steps_per_quarter=None, steps_per_second=None, name=None):
    super(Quantizer, self).__init__(name=name)
    if (steps_per_quarter is not None) == (steps_per_second is not None):
      raise ValueError(
          'Exactly one of steps_per_quarter or steps_per_second must be set.')
    self._steps_per_quarter = steps_per_quarter
    self._steps_per_second = steps_per_second

  def transform(self, note_sequence):
    try:
      if self._steps_per_quarter is not None:
        quantized_sequence = sequences_lib.quantize_note_sequence(
            note_sequence, self._steps_per_quarter)
      else:
        quantized_sequence = sequences_lib.quantize_note_sequence_absolute(
            note_sequence, self._steps_per_second)
      return [quantized_sequence]
    except sequences_lib.MultipleTimeSignatureException as e:
      tf.logging.warning('Multiple time signatures in NoteSequence %s: %s',
                         note_sequence.filename, e)
      self._set_stats([statistics.Counter(
          'sequences_discarded_because_multiple_time_signatures', 1)])
      return []
    except sequences_lib.MultipleTempoException as e:
      tf.logging.warning('Multiple tempos found in NoteSequence %s: %s',
                         note_sequence.filename, e)
      self._set_stats([statistics.Counter(
          'sequences_discarded_because_multiple_tempos', 1)])
      return []
    except sequences_lib.BadTimeSignatureException as e:
      tf.logging.warning('Bad time signature in NoteSequence %s: %s',
                         note_sequence.filename, e)
      self._set_stats([statistics.Counter(
          'sequences_discarded_because_bad_time_signature', 1)])
      return []


class SustainPipeline(NoteSequencePipeline):
  """Applies sustain pedal control changes to a NoteSequence."""

  def transform(self, note_sequence):
    return [sequences_lib.apply_sustain_control_changes(note_sequence)]


class TranspositionPipeline(NoteSequencePipeline):
  """Creates transposed versions of the input NoteSequence."""

  def __init__(self, transposition_range, name=None):
    """Creates a TranspositionPipeline.

    Args:
      transposition_range: Collection of integer pitch steps to transpose.
      name: Pipeline name.
    """
    super(TranspositionPipeline, self).__init__(name=name)
    self._transposition_range = transposition_range

  def transform(self, sequence):
    stats = dict([(state_name, statistics.Counter(state_name)) for state_name in
                  ['skipped_due_to_range_exceeded',
                   'transpositions_generated']])

    for text_annotation in sequence.text_annotations:
      if text_annotation.annotation_type == CHORD_SYMBOL:
        tf.logging.warn('Chord symbols ignored by TranspositionPipeline.')
        break

    transposed = []
    for amount in self._transposition_range:
      if amount == 0:
        transposed.append(sequence)
      else:
        ts = self._transpose(sequence, amount, stats)
        if ts is not None:
          transposed.append(ts)

    stats['transpositions_generated'].increment(len(transposed))
    self._set_stats(stats.values())
    return transposed

  @staticmethod
  def _transpose(ns, amount, stats):
    """Transposes a note sequence by the specified amount."""
    ts = copy.deepcopy(ns)
    for note in ts.notes:
      note.pitch += amount
      if (note.pitch < constants.MIN_MIDI_PITCH or
          note.pitch > constants.MAX_MIDI_PITCH):
        stats['skipped_due_to_range_exceeded'].increment()
        return None
    return ts
