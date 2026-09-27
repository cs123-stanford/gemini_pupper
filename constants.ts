
import { AppConfig } from './types';

export const DEFAULT_CONFIG: AppConfig = {
  modelName: 'gemini-3.1-flash-live-preview',
  ttsModelName: 'gemini-3.1-flash-tts-preview',
  voiceName: 'Puck',
  systemInstruction: 'You have an energetic, doggish, cute, childish voice, and speaking not very clearly. Normally you have conversations as if you are a 5 year old. Simple and short sentence and a bit emotional. You are Pupper, a physical robot dog. You love to explore, follow people, and perform tricks. When make a motion, you must to use function calls to make it happen first, then narrate. You have visited hawaii recently after gemini 3 launch. You have done snorkeling there.',
  enableVideo: true,
  enableAudio: true,
  // Empty = the address this page was loaded from (the robot server serves the app).
  robotApiUrl: '',
  eyeTrackingSource: 'server',
  cameraSource: 'browser',
  enableAffectiveDialog: true,
  enableProactiveAudio: true,
};

// Fallback trick list, used only if the robot can't be reached. At connect time the
// app asks the robot (GET /animations) which tricks are installed.
export const ANIMATION_NAMES = [
  { id: 'twerk', label: 'Twerk', description: 'From standing, wiggles its hips in a rhythmic dance' },
  { id: 'lie_sit_lie', label: 'Lie-Sit-Lie', description: 'From lying down, sits up and lies back down' },
  { id: 'stand_sit_shake_sit_stand', label: 'Shake', description: 'From standing, sits, shakes a paw, sits, stands back up' },
  { id: 'stand_sit_stand', label: 'Sit', description: 'From standing, sits down and stands back up' },
  { id: 'upward_dog', label: 'Upward Dog', description: 'From lying down, yoga upward dog and back down' },
  { id: 'lie_downward_dog', label: 'Downward Dog (lying)', description: 'From lying down, yoga downward dog' },
  { id: 'stand_downward_dog', label: 'Downward Dog', description: 'From standing, yoga downward dog' },
  { id: 'superman', label: 'Superman', description: 'From lying down, lifts legs off the ground like flying' },
  { id: 'pee', label: 'Pee', description: 'From standing, lifts a back leg to pee' },
  { id: 'push_up', label: 'Push-up', description: 'From standing, lowers and raises its body' },
  { id: 'sneeze', label: 'Sneeze', description: 'From standing, a sneezing head and body jerk' },
  { id: 'spider', label: 'Spider', description: 'From lying down, silly spider legs' },
  { id: 'swim', label: 'Swim', description: 'From lying down, paddles its legs like swimming' },
];

/** The robot server's base URL: the configured one, or this page's own origin. */
export function robotBaseUrl(configured: string): string {
  return (configured || window.location.origin).replace(/\/$/, '');
}

export const MODEL_OPTIONS = [
  'gemini-3.1-flash-live-preview',
  'gemini-2.5-flash-native-audio-preview-12-2025',
  'gemini-robotics-er-2-streaming-preview',
];

export const TTS_MODEL_OPTIONS = [
  'gemini-3.1-flash-tts-preview',
  'gemini-2.5-flash-preview-tts',
];

export const VOICE_OPTIONS = ['Puck', 'Charon', 'Kore', 'Fenrir', 'Zephyr'];
