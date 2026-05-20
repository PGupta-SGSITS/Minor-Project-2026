import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
import pandas as pd
from lstm_model import _registry
from ppg_extraction import *
import numpy as np

data = pd.read_csv('dataset/video_data.csv')
_registry._load_enhanced()
model = _registry.enhanced_model
fs = _registry.enhanced_feature_scaler
ys = _registry.enhanced_y_scaler

for i in range(3):
    row = data.iloc[i]
    frames, effective_fps = extract_frames(row['video_path'])
    signal = extract_ppg_signal(frames)
    signal = remove_motion_artifacts(signal)
    signal = adaptive_bandpass_filter(signal)
    signal = smooth_signal(signal)
    signal = normalize_signal(signal)
    
    if len(signal) < 120:
        signal = np.pad(signal, (0, 120 - len(signal)), mode='reflect')
    else:
        signal = signal[:120]
        
    peaks = detect_peaks(signal)
    features = extract_extended_features(signal, peaks)
    
    sf = fs.transform([features])
    inp_sig = signal.reshape(1, 120, 1)
    
    # NORMAL PREDICT
    pred = model.predict([inp_sig, sf], verbose=0)
    pred_g = ys.inverse_transform(pred)[0][0]
    
    # DROPOUT PREDICT
    pred_mc = model([inp_sig, sf], training=True).numpy()[0][0]
    pred_mc_g = ys.inverse_transform([[pred_mc]])[0][0]
    
    print(f"[{row['video_path']}] True: {row['glucose']} | Normal Pred: {pred_g:.2f} | MC Dropout Pred: {pred_mc_g:.2f}")
