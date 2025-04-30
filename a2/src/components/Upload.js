import { useState, useRef, useEffect } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import '../styles/Upload.css';

/**
 * Upload component for ParkSense
 * Handles camera capture and text uploads to the backend
 */
function Upload() {
  const [image, setImage] = useState(null);
  const [preview, setPreview] = useState(null);
  const [text, setText] = useState('');
  const [error, setError] = useState('');
  const [result, setResult] = useState('');
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const [stream, setStream] = useState(null);

  // Initialize camera
  useEffect(() => {
    async function startCamera() {
      try {
        const mediaStream = await navigator.mediaDevices.getUserMedia({ 
          video: { facingMode: 'environment' } 
        });
        setStream(mediaStream);
        if (videoRef.current) {
          videoRef.current.srcObject = mediaStream;
        }
      } catch (err) {
        setError('Error accessing camera: ' + err.message);
      }
    }
    startCamera();

    return () => {
      if (stream) {
        stream.getTracks().forEach(track => track.stop());
      }
    };
  }, []);

  // Handle image capture
  const handleCapture = () => {
    if (!videoRef.current || !canvasRef.current) return;

    const context = canvasRef.current.getContext('2d');
    canvasRef.current.width = videoRef.current.videoWidth;
    canvasRef.current.height = videoRef.current.videoHeight;
    context.drawImage(videoRef.current, 0, 0);

    const imageData = canvasRef.current.toDataURL('image/jpeg');
    setPreview(imageData);

    // Convert data URL to Blob for upload
    fetch(imageData)
      .then(res => res.blob())
      .then(blob => setImage(blob));
  };

  // Handle image upload
  const handleImageSubmit = async (e) => {
    e.preventDefault();
    if (!image) {
      setError('Please capture an image.');
      return;
    }

    const formData = new FormData();
    formData.append('file', image, 'captured-image.jpg');

    try {
      const response = await axios.post('http://localhost:5000/upload', formData);
      setResult(`Plate: ${response.data.plate_number} | Status: ${response.data.status} | Time: ${response.data.timestamp}`);
      setImage(null);
      setPreview(null);
      setError('');
    } catch (err) {
      setError(err.response?.data?.error || 'Error uploading image.');
    }
  };

  // Handle text submit
  const handleTextSubmit = async (e) => {
    e.preventDefault();
    if (!text.trim()) {
      setError('Please enter some text.');
      return;
    }

    try {
      const response = await axios.post('http://localhost:5000/text', { text });
      setResult(`Response: ${response.data.message} | Time: ${response.data.timestamp}`);
      setText('');
      setError('');
    } catch (err) {
      setError(err.response?.data?.error || 'Error submitting text.');
    }
  };

  return (
    <div className="upload">
      <header>
        <h1>Capture Car Image or Details</h1>
      </header>
      <main>
        <div className="input-container">
          <form onSubmit={handleImageSubmit}>
            <video ref={videoRef} autoPlay playsInline style={{ width: '100%', maxWidth: '500px' }} />
            <canvas ref={canvasRef} style={{ display: 'none' }} />
            <button type="button" onClick={handleCapture}>Capture Image</button>
            <button type="submit">Upload Image</button>
          </form>
          {preview && <img src={preview} alt="Captured Preview" style={{ maxWidth: '500px' }} />}
          {error && <div className="error-message">{error}</div>}
        </div>
        <div className="input-container">
          <form onSubmit={handleTextSubmit}>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows="4"
              placeholder="Describe the car or parking details"
              aria-label="Enter car or parking details"
            />
            <button type="submit">Submit Text</button>
          </form>
        </div>
        {result && <div className="result">{result}</div>}
        <Link to="/" className="back-link">← Back to Home</Link>
      </main>
    </div>
  );
}

export default Upload;