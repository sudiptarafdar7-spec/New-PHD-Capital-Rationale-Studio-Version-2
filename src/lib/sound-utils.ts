// Sound utility for playing notification sounds

/**
 * Plays a pleasant bell sound using Web Audio API
 * @param type - 'success' for completion bell, 'notification' for step completion
 */
export const playBellSound = (type: 'success' | 'notification' = 'notification') => {
  try {
    const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
    
    // Create oscillator for the bell sound
    const oscillator = audioContext.createOscillator();
    const gainNode = audioContext.createGain();
    
    // Connect nodes
    oscillator.connect(gainNode);
    gainNode.connect(audioContext.destination);
    
    if (type === 'success') {
      // Success bell: Higher pitch, longer sustain, two-tone
      const now = audioContext.currentTime;
      
      // First tone
      oscillator.frequency.setValueAtTime(800, now);
      oscillator.frequency.exponentialRampToValueAtTime(1000, now + 0.1);
      
      // Volume envelope for success
      gainNode.gain.setValueAtTime(0, now);
      gainNode.gain.linearRampToValueAtTime(0.3, now + 0.01);
      gainNode.gain.exponentialRampToValueAtTime(0.01, now + 0.5);
      
      oscillator.type = 'sine';
      oscillator.start(now);
      oscillator.stop(now + 0.5);
      
      // Second tone (higher)
      setTimeout(() => {
        const oscillator2 = audioContext.createOscillator();
        const gainNode2 = audioContext.createGain();
        oscillator2.connect(gainNode2);
        gainNode2.connect(audioContext.destination);
        
        const now2 = audioContext.currentTime;
        oscillator2.frequency.setValueAtTime(1200, now2);
        oscillator2.frequency.exponentialRampToValueAtTime(1400, now2 + 0.1);
        
        gainNode2.gain.setValueAtTime(0, now2);
        gainNode2.gain.linearRampToValueAtTime(0.3, now2 + 0.01);
        gainNode2.gain.exponentialRampToValueAtTime(0.01, now2 + 0.5);
        
        oscillator2.type = 'sine';
        oscillator2.start(now2);
        oscillator2.stop(now2 + 0.5);
      }, 100);
    } else {
      // Notification bell: Standard pitch, shorter
      const now = audioContext.currentTime;
      
      oscillator.frequency.setValueAtTime(600, now);
      oscillator.frequency.exponentialRampToValueAtTime(800, now + 0.1);
      
      // Volume envelope
      gainNode.gain.setValueAtTime(0, now);
      gainNode.gain.linearRampToValueAtTime(0.25, now + 0.01);
      gainNode.gain.exponentialRampToValueAtTime(0.01, now + 0.3);
      
      oscillator.type = 'sine';
      oscillator.start(now);
      oscillator.stop(now + 0.3);
    }
  } catch (error) {
    console.warn('Audio playback not supported:', error);
  }
};

/**
 * Plays a completion bell sound (same as success)
 */
export const playCompletionBell = () => {
  playBellSound('notification');
};

/**
 * Plays a success bell sound (celebration)
 */
export const playSuccessBell = () => {
  playBellSound('success');
};
