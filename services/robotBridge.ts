import { MoveCommand, SystemStatus } from "../types";
import { robotBaseUrl } from "../constants";

// This service talks to the Python FastAPI backend running on the robot
// (robot/server.py). Every POST returns {success, message}: pass it on to Gemini
// as the tool result. (Provided plumbing: the tools themselves are yours, in
// geminiLive.ts.)
class RobotBridge {
  readonly baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = robotBaseUrl(baseUrl);
  }

  private async request(endpoint: string, method: 'GET' | 'POST', body?: any, returnBlob: boolean = false) {
    try {
      const options: RequestInit = {
        method,
        headers: body && method === 'POST' ? { 'Content-Type': 'application/json' } : {},
      };

      if (body && method === 'POST') {
        options.body = JSON.stringify(body);
      }

      const response = await fetch(`${this.baseUrl}${endpoint}`, options);

      if (!response.ok) {
        throw new Error(`robot server returned HTTP ${response.status} for ${endpoint}`);
      }
      
      if (returnBlob) {
        return await response.blob();
      }
      return await response.json();
    } catch (e) {
      // Suppress log spam for polling
      if(endpoint !== '/system/status' && endpoint !== '/camera/image') {
         console.error(`[RobotBridge] Error calling ${endpoint}`, e);
      }
      return { success: false, message: `robot unreachable: ${(e as Error)?.message || e}` };
    }
  }

  async getSystemStatus(): Promise<SystemStatus | null> {
    const res = await this.request('/system/status', 'GET');
    if (res && !res.error) {
      console.log("Returned value from /system/status is", JSON.stringify(res, null, 2));
      return res as SystemStatus;
    }
    return null;
  }
  
  async getCameraImage(): Promise<Blob | null> {
      try {
          const blob = await this.request('/camera/image', 'GET', undefined, true);
          if (blob instanceof Blob) {
              return blob;
          }
      } catch (e) {}
      return null;
  }

  async queueActivateWalking() {
    return this.request('/walking/activate', 'POST');
  }

  async queueDeactivate() {
    return this.request('/walking/deactivate', 'POST');
  }

  async queueMove(cmd: MoveCommand) {
    // Map internal MoveCommand to API MoveVelocityRequest
    const body = {
      forward_backward_velocity: cmd.vx,
      right_left_velocity: cmd.vy,
      turning_velocity: cmd.wz,
      duration: cmd.duration
    };
    return this.request('/move/velocity', 'POST', body);
  }

  async moveDirection(heading: number, speed: number, duration: number) {
    return this.request('/move/direction', 'POST', { heading, speed, duration });
  }

  async queueStop() {
    return this.request('/queue/stop', 'POST');
  }

  async queueWait(duration: number) {
    return this.request('/queue/wait', 'POST', { duration });
  }

  async queueReset() {
    return this.request('/queue/reset', 'POST');
  }

  async immediateStop() {
    return this.request('/stop/immediate', 'POST');
  }

  async queueAnimation(name: string) {
    return this.request('/animation', 'POST', { animation_name: name });
  }

  async getLimits() {
    return this.request('/limits', 'GET');
  }

  async getQueueStatus() {
    return this.request('/queue/status', 'GET');
  }

  async trickAction(action: string) {
    return this.request('/trick_action', 'POST', { action });
  }

  /** Part 3: POST /dance with your list of moves (see robot/server.py DanceStep). */
  async dance(moves: { move: string; hold_s?: number }[]) {
    return this.request('/dance', 'POST', { moves });
  }

  async getTrickActions() {
    return this.request('/trick_actions', 'GET');
  }

  async getAnimations() {
    return this.request('/animations', 'GET');
  }

  async setVolume(volume: number) {
    return this.request('/system/volume', 'POST', { volume });
  }

  async checkMode() {
    return this.request('/system/mode', 'GET');
  }

  async setFollowMode(enabled: boolean) {
    const endpoint = enabled ? '/following/activate' : '/following/deactivate';
    return this.request(endpoint, 'POST');
  }
}

export default RobotBridge;