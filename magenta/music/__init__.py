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

"""Imports objects from music modules into the top-level music namespace."""

from magenta.music.constants import *  # pylint: disable=wildcard-import

from magenta.music.drums_encoder_decoder import MultiDrumOneHotEncoding

from magenta.music.drums_lib import DrumTrack
from magenta.music.drums_lib import extract_drum_tracks
from magenta.music.drums_lib import midi_file_to_drum_track

from magenta.music.encoder_decoder import EventSequenceEncoderDecoder
from magenta.music.encoder_decoder import LookbackEventSequenceEncoderDecoder
from magenta.music.encoder_decoder import OneHotEncoding
from magenta.music.encoder_decoder import OneHotEventSequenceEncoderDecoder

from magenta.music.events_lib import NonIntegerStepsPerBarException

from magenta.music.melodies_lib import BadNoteException
from magenta.music.melodies_lib import extract_melodies
from magenta.music.melodies_lib import Melody
from magenta.music.melodies_lib import midi_file_to_melody
from magenta.music.melodies_lib import PolyphonicMelodyException

from magenta.music.melody_encoder_decoder import KeyMelodyEncoderDecoder
from magenta.music.melody_encoder_decoder import MelodyOneHotEncoding

from magenta.music.midi_io import midi_file_to_sequence_proto
from magenta.music.midi_io import midi_to_sequence_proto
from magenta.music.midi_io import MIDIConversionError
from magenta.music.midi_io import sequence_proto_to_midi_file
from magenta.music.midi_io import sequence_proto_to_pretty_midi

from magenta.music.midi_synth import fluidsynth
from magenta.music.midi_synth import synthesize

from magenta.music.model import BaseModel

from magenta.music.musicxml_parser import MusicXMLDocument
from magenta.music.musicxml_parser import MusicXMLParseException

from magenta.music.musicxml_reader import musicxml_file_to_sequence_proto
from magenta.music.musicxml_reader import musicxml_to_sequence_proto
from magenta.music.musicxml_reader import MusicXMLConversionError

from magenta.music.notebook_utils import play_sequence

from magenta.music.sequence_generator import BaseSequenceGenerator
from magenta.music.sequence_generator import SequenceGeneratorException

from magenta.music.sequence_generator_bundle import GeneratorBundleParseException
from magenta.music.sequence_generator_bundle import read_bundle_file

from magenta.music.sequences_lib import BadTimeSignatureException
from magenta.music.sequences_lib import MultipleTempoException
from magenta.music.sequences_lib import MultipleTimeSignatureException
from magenta.music.sequences_lib import NegativeTimeException
from magenta.music.sequences_lib import extract_subsequence
from magenta.music.sequences_lib import QuantizedSequence
