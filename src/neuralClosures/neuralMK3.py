'''
Derived network class "MK3" for the neural entropy closure.
Author: Steffen Schotthöfer
Version: 0.0
Date 29.10.2020
'''
from .neuralBase import neuralBase
import numpy as np
import tensorflow as tf
from tensorflow import keras
from tensorflow import Tensor
import csv

'''
import pandas as pd
import sphericalquadpy as sqp
from joblib import Parallel, delayed
import multiprocessing
'''


class neuralMK3(neuralBase):
    '''
    MK1 Model: Train u to alpha
    Training data generation: b) read solver data from file
    Loss function:  MSE between alpha and real_alpha
    '''

    def __init__(self, polyDegree=0, spatialDim=1, folderName="testFolder", lossCombi=0, width=10, depth=5,
                 normalized=False):
        if (folderName == "testFolder"):
            customFolderName = "MK1_N" + str(polyDegree) + "_D" + str(spatialDim)
        else:
            customFolderName = folderName

        super(neuralMK3, self).__init__(normalized, polyDegree, spatialDim, width, depth, lossCombi,
                                        customFolderName)

        self.model = self.createModel()

    def createModel(self):
        inputDim = self.getIdxSphericalHarmonics(self.polyDegree, self.polyDegree) + 1

        # Define Residual block
        def residual_block(x: Tensor) -> Tensor:
            y = keras.layers.Dense(20, activation="relu")(x)
            y = keras.layers.Dense(20, activation="relu")(y)
            y = keras.layers.Dense(20, activation="relu")(y)

            out = keras.layers.Add()([x, y])
            out = keras.layers.ReLU()(out)
            out = keras.layers.BatchNormalization()(out)
            return out

        # Define the input
        # Number of basis functions used:

        input_ = keras.Input(shape=(inputDim,))

        # Hidden layers
        hidden = keras.layers.Dense(20, activation="relu")(input_)

        # Resnet Layers
        hidden = residual_block(hidden)
        hidden = residual_block(hidden)
        hidden = residual_block(hidden)
        hidden = residual_block(hidden)

        hidden = keras.layers.Dense(20, activation="relu")(hidden)

        # Define the ouput
        output_ = keras.layers.Dense(inputDim)(hidden)

        # Create the model
        model = keras.Model(name="MK3closure", inputs=[input_], outputs=[output_])
        model.summary()

        # alternative way of training
        # model.compile(loss=cLoss_FONC_varD(quadOrder,BasisDegree), optimizer='adam')#, metrics=[custom_loss1dMB, custom_loss1dMBPrime])
        model.compile(loss=tf.keras.losses.MeanSquaredError(), optimizer=self.opt, metrics=['mean_absolute_error'])

        return model

    def selectTrainingData(self):
        return [True, True, False]

    def getIdxSphericalHarmonics(self, k, l):
        # Returns the global idx from spherical harmonics indices
        return l * l + k + l
