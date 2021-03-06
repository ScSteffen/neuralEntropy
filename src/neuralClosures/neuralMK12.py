'''
Network class "MK12" for the neural entropy closure.
As MK11, but dense network instead of ICNN
Author: Steffen Schotthöfer
Version: 0.0
Date 09.04.2020
'''
from .neuralBase import neuralBase
from .neuralBase import LossAndErrorPrintingCallback

import numpy as np
import tensorflow as tf
from tensorflow import keras as keras
from tensorflow.keras import layers
from tensorflow.keras.constraints import NonNeg
from tensorflow import Tensor
from src import math


class neuralMK12(neuralBase):

    def __init__(self, polyDegree=0, spatialDim=1, folderName="testFolder", lossCombi=0, width=10, depth=5,
                 normalized=False):
        if (folderName == "testFolder"):
            customFolderName = "MK11_N" + str(polyDegree) + "_D" + str(spatialDim)
        else:
            customFolderName = folderName

        super(neuralMK12, self).__init__(normalized, polyDegree, spatialDim, width, depth, lossCombi,
                                         customFolderName)

        self.model = self.createModel()

    def createModel(self):

        layerDim = self.modelWidth

        # Weight initializer
        initializerNonNeg = tf.keras.initializers.RandomUniform(minval=0, maxval=0.5, seed=None)
        initializer = tf.keras.initializers.RandomUniform(minval=-0.5, maxval=0.5, seed=None)
        # Weight regularizer
        l1l2Regularizer = tf.keras.regularizers.L1L2(l1=0.0, l2=0.0)  # L1 + L2 penalties

        ### build the core network with icnn closure architecture ###
        input_ = keras.Input(shape=(self.inputDim,))
        # First Layer is a std dense layer
        hidden = layers.Dense(layerDim, activation="softplus",
                              kernel_initializer=initializer,
                              kernel_regularizer=l1l2Regularizer,
                              bias_initializer='zeros',
                              name="first_dense"
                              )(input_)
        # other layers are convexLayers
        for idx in range(0, self.modelDepth):
            hidden = layers.Dense(self.modelWidth, activation="softplus",
                                  kernel_initializer=initializer,
                                  kernel_regularizer=l1l2Regularizer,
                                  bias_initializer='zeros',
                                  name="dense_" + str(idx)
                                  )(hidden)
        output_ = layers.Dense(1, activation="linear",
                               kernel_initializer=initializer,
                               kernel_regularizer=l1l2Regularizer,
                               bias_initializer='zeros',
                               name="dense_output"
                               )(hidden)  # outputlayer

        # Create the core model
        coreModel = keras.Model(inputs=[input_], outputs=[output_], name="Icnn_closure")

        # build model
        model = sobolevModel(coreModel, polyDegree=self.polyDegree, name="sobolev_icnn_wrapper")

        batchSize = 2  # dummy entry
        model.build(input_shape=(batchSize, self.inputDim))

        # model.compile(loss=tf.keras.losses.MeanSquaredError(),
        #              # loss={'output_1': tf.keras.losses.MeanSquaredError()},
        #              # loss_weights={'output_1': 1, 'output_2': 0},
        #              optimizer='adam',
        #              metrics=['mean_absolute_error', 'mean_squared_error'])
        model.compile(
            loss={'output_1': tf.keras.losses.MeanSquaredError(), 'output_2': tf.keras.losses.MeanSquaredError()},
            loss_weights={'output_1': 1, 'output_2': 1},
            optimizer='adam',
            metrics=['mean_absolute_error'])

        # model.summary()

        # tf.keras.utils.plot_model(model, to_file=self.filename + '/modelOverview', show_shapes=True,
        # show_layer_names = True, rankdir = 'TB', expand_nested = True)

        return model

    def call_training(self, val_split=0.1, epoch_size=2, batch_size=128, verbosity_mode=1, callback_list=[]):
        '''
        Calls training depending on the MK model
        '''
        xData = self.trainingData[0]
        yData = [self.trainingData[2], self.trainingData[1]]
        self.model.fit(x=xData, y=yData,
                       validation_split=val_split, epochs=epoch_size,
                       batch_size=batch_size, verbose=verbosity_mode,
                       callbacks=callback_list, shuffle=True)
        return self.history

    def selectTrainingData(self):
        return [True, True, True]

    def trainingDataPostprocessing(self):
        return 0

    def callNetwork(self, u_complete):
        """
        brief: Only works for maxwell Boltzmann entropy so far.
        nS = batchSize
        N = basisSize
        nq = number of quadPts

        input: u_complete, dims = (nS x N)
        returns: alpha_complete_predicted, dim = (nS x N)
                 u_complete_reconstructed, dim = (nS x N)
                 h_predicted, dim = (nS x 1)
        """
        u_reduced = u_complete[:, 1:]  # chop of u_0
        [h_predicted, alpha_predicted] = self.model(u_reduced)
        alpha_complete_predicted = self.model.reconstruct_alpha(alpha_predicted)
        u_complete_reconstructed = self.model.reconstruct_u(alpha_complete_predicted)

        return [u_complete_reconstructed, alpha_complete_predicted, h_predicted]


class sobolevModel(tf.keras.Model):
    # Sobolev implies, that the model outputs also its derivative
    def __init__(self, coreModel, polyDegree=1, **opts):
        super(sobolevModel, self).__init__()
        # Member is only the model we want to wrap with sobolev execution
        self.coreModel = coreModel  # must be a compiled tensorflow model

        # Create quadrature and momentBasis. Currently only for 1D problems
        self.polyDegree = polyDegree
        self.nq = 100
        [quadPts, quadWeights] = math.qGaussLegendre1D(self.nq)  # dims = nq
        self.quadPts = tf.constant(quadPts, shape=(1, self.nq), dtype=tf.float32)  # dims = (batchSIze x N x nq)
        self.quadWeights = tf.constant(quadWeights, shape=(1, self.nq),
                                       dtype=tf.float32)  # dims = (batchSIze x N x nq)
        mBasis = math.computeMonomialBasis1D(quadPts, self.polyDegree)  # dims = (N x nq)
        self.inputDim = mBasis.shape[0]
        self.momentBasis = tf.constant(mBasis, shape=(self.inputDim, self.nq),
                                       dtype=tf.float32)  # dims = (batchSIze x N x nq)

    def call(self, x, training=False):
        """
        Defines the sobolev execution
        """

        with tf.GradientTape() as grad_tape:
            grad_tape.watch(x)
            h = self.coreModel(x)
        alpha = grad_tape.gradient(h, x)

        return [h, alpha]

    def callDerivative(self, x, training=False):
        with tf.GradientTape() as grad_tape:
            grad_tape.watch(x)
            y = self.coreModel(x)
        derivativeNet = grad_tape.gradient(y, x)

        return derivativeNet

    def reconstruct_alpha(self, alpha):
        """
        brief: Only works for maxwell Boltzmann entropy so far.
        nS = batchSize
        N = basisSize
        nq = number of quadPts

        input: alpha, dims = (nS x N-1)
               m    , dims = (N x nq)
               w    , dims = nq
        returns alpha_complete = [alpha_0,alpha], dim = (nS x N), where alpha_0 = - ln(<exp(alpha*m)>)
        """
        tmp = tf.math.exp(tf.tensordot(alpha, self.momentBasis[1:, :], axes=([1], [0])))  # tmp = alpha * m
        alpha_0 = -tf.math.log(tf.tensordot(tmp, self.quadWeights, axes=([1], [1])))  # ln(<tmp>)
        return tf.concat([alpha_0, alpha], axis=1)  # concat [alpha_0,alpha]

    def reconstruct_u(self, alpha):
        """
        nS = batchSize
        N = basisSize
        nq = number of quadPts

        input: alpha, dims = (nS x N)
               m    , dims = (N x nq)
               w    , dims = nq
        returns u = <m*eta_*'(alpha*m)>, dim = (nS x N)
        """
        # Currently only for maxwell Boltzmann entropy
        f_quad = tf.math.exp(tf.tensordot(alpha, self.momentBasis, axes=([1], [0])))  # alpha*m
        tmp = tf.math.multiply(f_quad, self.quadWeights)  # f*w
        return tf.tensordot(tmp, self.momentBasis[:, :], axes=([1], [1]))  # f * w * momentBasis
