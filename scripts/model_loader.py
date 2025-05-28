import tensorrt as trt
import numpy as np
import pycuda.driver as cuda
import pycuda.autoinit
import os

# TensorRT logger for error handling
TRT_LOGGER = trt.Logger(trt.Logger.WARNING)

class TensorRTModel:
    def __init__(self, trt_path):
        """Initialize and load a TensorRT model from a .trt file."""
        self.engine = None
        self.context = None
        self.inputs = []
        self.outputs = []
        self.bindings = []
        self.stream = cuda.Stream()
        
        # Load the TensorRT engine
        if not os.path.exists(trt_path):
            raise FileNotFoundError(f"TensorRT engine file not found at {trt_path}. Ensure the model has been converted using trtexec.")
        
        with open(trt_path, 'rb') as f, trt.Runtime(TRT_LOGGER) as runtime:
            self.engine = runtime.deserialize_cuda_engine(f.read())
        
        if self.engine is None:
            raise RuntimeError(f"Failed to load TensorRT engine from {trt_path}.")
        
        # Create execution context
        self.context = self.engine.create_execution_context()
        print(f"Loaded TensorRT model from {trt_path}")

    def allocate_buffers(self, input_shape):
        """Allocate buffers for model input and output."""
        self.inputs = []
        self.outputs = []
        self.bindings = []
        
        for binding in self.engine:
            size = trt.volume(self.engine.get_binding_shape(binding)) * self.engine.max_batch_size
            dtype = trt.nptype(self.engine.get_binding_dtype(binding))
            # Allocate host and device memory
            host_mem = cuda.pagelocked_empty(size, dtype)
            device_mem = cuda.mem_alloc(host_mem.nbytes)
            self.bindings.append(int(device_mem))
            if self.engine.binding_is_input(binding):
                self.inputs.append({'host': host_mem, 'device': device_mem})
            else:
                self.outputs.append({'host': host_mem, 'device': device_mem})

    def infer(self, input_data):
        """Run inference on the input data using the loaded TensorRT model."""
        # Copy input data to host memory
        np.copyto(self.inputs[0]['host'], input_data.ravel())
        
        # Transfer input data to device
        cuda.memcpy_htod_async(self.inputs[0]['device'], self.inputs[0]['host'], self.stream)
        
        # Execute inference
        self.context.execute_async_v2(bindings=self.bindings, stream_handle=self.stream.handle)
        
        # Transfer output data back to host
        for out in self.outputs:
            cuda.memcpy_dtoh_async(out['host'], out['device'], self.stream)
        
        # Synchronize the stream
        self.stream.synchronize()
        
        # Reshape outputs to match the model's output shape
        return [out['host'].reshape(self.engine.get_binding_shape(i + 1)) for i, out in enumerate(self.outputs)]