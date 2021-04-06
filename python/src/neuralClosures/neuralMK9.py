'''
Derived network class "MK9" for the neural entropy closure.
Dense neural Network with polynomial activations.
Author: Steffen Schotthöfer
Version: 0.0
Date 29.03.2020
'''
from .neuralBase import neuralBase
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers
from tensorflow import Tensor
from tensorflow.keras.constraints import NonNeg

from tensorflow.keras import backend as K


class neuralMK9(neuralBase):
    '''
    MK4 Model: Train u to alpha
    Training data generation: b) read solver data from file: Uses C++ Data generator
    Loss function:  MSE between h_pred and real_h
    '''

    def __init__(self, polyDegree=0, spatialDim=0, folderName="testFolder", optimizer='adam'):
        if (folderName == "testFolder"):
            tempString = "MK9_N" + str(polyDegree) + "_D" + str(spatialDim)
        else:
            tempString = folderName

        self.polyDegree = polyDegree
        self.spatialDim = spatialDim

        # --- Determine inputDim by MaxDegree ---
        if (spatialDim == 1):
            self.inputDim = polyDegree + 1
        elif (spatialDim == 3):
            if (self.polyDegree == 0):
                self.inputDim = 1
            elif (self.polyDegree == 1):
                self.inputDim = 4
            else:
                raise ValueError("Polynomial degeree higher than 1 not supported atm")
        elif (spatialDim == 2):
            if (self.polyDegree == 0):
                self.inputDim = 1
            elif (self.polyDegree == 1):
                self.inputDim = 3
            else:
                raise ValueError("Polynomial degeree higher than 1 not supported atm")
        else:
            raise ValueError("Saptial dimension other than 1,2 or 3 not supported atm")

        self.opt = optimizer
        self.model = self.createModel()
        self.filename = "models/" + tempString

    def createModel(self):

        layerDim = 20

        # Weight initializer
        initializerNonNeg = tf.keras.initializers.RandomUniform(minval=0, maxval=0.5, seed=None)
        initializer = tf.keras.initializers.RandomUniform(minval=-0.5, maxval=0.5, seed=None)

        # custom output function (quadratic)
        def quadActivation(x):
            return tf.math.multiply(x, x)

        def convexLayer(layerInput_z: Tensor, netInput_x: Tensor) -> Tensor:
            # Weighted sum of previous layers output plus bias
            weightedNonNegSum_z = layers.Dense(layerDim, kernel_constraint=NonNeg(), activation=None,
                                               kernel_initializer=initializerNonNeg,
                                               use_bias=True,
                                               bias_initializer='zeros'
                                               # name='in_z_NN_Dense'
                                               )(layerInput_z)
            # Weighted sum of network input
            weightedSum_x = layers.Dense(layerDim, activation=None,
                                         kernel_initializer=initializer,
                                         use_bias=False
                                         # name='in_x_Dense'
                                         )(netInput_x)
            # Wz+Wx+b
            intermediateSum = layers.Add()([weightedSum_x, weightedNonNegSum_z])

            # activation
            out = quadActivation(intermediateSum)
            # batch normalization
            # out = layers.BatchNormalization()(out)
            return out

        def convexLayerOutput(layerInput_z: Tensor, netInput_x: Tensor) -> Tensor:
            # Weighted sum of previous layers output plus bias
            weightedNonNegSum_z = layers.Dense(1, kernel_constraint=NonNeg(), activation=None,
                                               kernel_initializer=initializerNonNeg,
                                               use_bias=True,
                                               bias_initializer='zeros'
                                               # name='in_z_NN_Dense'
                                               )(layerInput_z)
            # Weighted sum of network input
            weightedSum_x = layers.Dense(1, activation=None,
                                         kernel_initializer=initializer,
                                         use_bias=False
                                         # name='in_x_Dense'
                                         )(netInput_x)
            # Wz+Wx+b
            intermediateSum = layers.Add()([weightedSum_x, weightedNonNegSum_z])

            # activation
            # out = tf.keras.activations.softplus(intermediateSum)
            # batch normalization
            # out = layers.BatchNormalization()(out)
            return intermediateSum

        # Number of basis functions used:
        input_ = keras.Input(shape=(self.inputDim,))

        ### Hidden layers ###
        # First Layer is a std dense layer
        hidden = layers.Dense(layerDim, activation="relu",
                              kernel_initializer=initializer,
                              bias_initializer='zeros'
                              )(input_)
        # other layers are convexLayers
        hidden = convexLayer(hidden, input_)
        hidden = convexLayer(hidden, input_)
        hidden = convexLayer(hidden, input_)
        hidden = convexLayer(hidden, input_)
        hidden = convexLayer(hidden, input_)
        output_ = convexLayerOutput(hidden, input_)  # outputlayer

        # Create the model
        model = keras.Model(inputs=[input_], outputs=[output_], name="ICNN")
        # model.summary()

        # model.compile(loss=cLoss_FONC_varD(quadOrder,BasisDegree), optimizer='adam')#, metrics=[custom_loss1dMB, custom_loss1dMBPrime])
        model.compile(loss="mean_squared_error", optimizer=self.opt, metrics=['mean_absolute_error'])

        return model

    def selectTrainingData(self):
        return [True, False, True]

    def trainingDataPostprocessing(self):
        # find the maximum of u_0
        u0Max = max(self.trainingData[0][:, 0])
        self.trainingData[0] / u0Max
        print("Training Data Scaled")
        return 0