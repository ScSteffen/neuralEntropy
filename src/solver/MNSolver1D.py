"""
brief: Testing ground for 1D moment solver
Author: Steffen Schotthöfer
Date: 17.05.2021
"""
import sys
import csv

sys.path.append('../..')
import numpy as np
import scipy.optimize
import matplotlib.pyplot as plt
from matplotlib import animation
from matplotlib.colors import LogNorm
import multiprocessing
import pandas as pd
from joblib import Parallel, delayed

# inpackage imports
# from neuralClosures.configModel import initNeuralClosure
from src import math
from src.neuralClosures.configModel import initNeuralClosure

num_cores = multiprocessing.cpu_count()


def main():
    solver = MNSolver1D(traditional=False, polyDegree=2)
    # solver.solveAnimation(maxIter=100)
    # solver.solveAnimationIterError(maxIter=100)
    # solver.solveIterError(maxIter=100)
    solver.solve(maxIter=2000)
    return 0


class MNSolver1D:

    def __init__(self, traditional=False, polyDegree=3):

        # Prototype for  spatialDim=1, polyDegree=2
        self.nSystem = polyDegree + 1
        self.polyDegree = polyDegree
        self.quadOrder = 10
        self.traditional = traditional
        [self.quadPts, self.quadWeights] = math.qGaussLegendre1D(self.quadOrder)  # dims = nq
        self.nq = self.quadWeights.size
        self.mBasis = math.computeMonomialBasis1D(self.quadPts, self.polyDegree)  # dims = (N x nq)
        self.inputDim = self.mBasis.shape[0]  # = self.nSystem

        # generate geometry
        self.x0 = -1.5
        self.x1 = 1.5
        self.nx = 50
        self.dx = (self.x1 - self.x0) / self.nx

        # physics (homogeneous)
        self.sigmaS = 1.0
        self.sigmaA = 0.0
        self.sigmaT = self.sigmaS + self.sigmaA

        # time
        self.tEnd = 1.0
        self.cfl = 0.3
        self.dt = self.cfl * self.dx

        # Solver variables Traditional
        self.u = self.ICperiodic()  # self.ICLinesource()  # periodic IC
        self.alpha = np.zeros((self.nSystem, self.nx))
        self.xFlux = np.zeros((self.nSystem, self.nx), dtype=float)
        self.h = np.zeros(self.nx)
        self.h2 = np.zeros(self.nx)

        self.u2 = self.ICperiodic()  # self.ICLinesource()  # self.ICperiodic()
        self.alpha2 = np.zeros((self.nSystem, self.nx))
        self.xFlux2 = np.zeros((self.nSystem, self.nx), dtype=float)
        # Neural closure
        self.neuralClosure = None
        if not self.traditional:
            if self.polyDegree == 2:
                self.neuralClosure = initNeuralClosure(modelNumber=11, polyDegree=2, spatialDim=1,
                                                       folderName="002_sim_M2_1D", lossCombi=2,
                                                       width=15, depth=7, normalized=True)
                self.neuralClosure.loadModel("../../models/002_sim_M2_1D")
            elif self.polyDegree == 3:
                self.neuralClosure = initNeuralClosure(modelNumber=13, polyDegree=3, spatialDim=1,
                                                       folderName="002_sim_M3_1D", lossCombi=2,
                                                       width=20, depth=7, normalized=True)
                self.neuralClosure.loadModel("../../models/002_sim_M3_1D")

        # Analysis variables
        self.errorMap = np.zeros((self.nSystem, self.nx))
        self.normErrorMap = np.zeros(self.nx)
        self.realizabilityMap = np.zeros(self.nx)
        columns = ['u0', 'u1', 'u2', 'alpha0', 'alpha1', 'alpha2', 'h']  # , 'realizable']
        self.dfErrPoints = pd.DataFrame(columns=columns)

        with open('00errorAnalysis1D.csv', 'w', newline='') as f:
            # create the csv writer
            writer = csv.writer(f)
            row = ["iter", "entropyOrig", "entropy"]
            writer.writerow(row)

    def ICperiodic(self):
        def sincos(x):
            return 1.5 + np.cos(2 * np.pi * x)

        uIc = np.zeros((self.nSystem, self.nx))

        for i in range(self.nx):
            xKoor = self.x0 + (i - 0.5) * self.dx
            uIc[0, i] = sincos(xKoor)
            uIc[1, i] = 0.0
            uIc[2, i] = 0.5 * uIc[0, i]

        return uIc

    def ICLinesource(self):
        def normal_dist(x, mean, sd):
            prob_density = (np.pi * sd) * np.exp(-0.5 * ((x - mean) / sd) ** 2)
            return prob_density

        def sincos(x):
            return 1.0 + 0.5 * np.cos(2 * np.pi * x)

        uIc = np.zeros((self.nSystem, self.nx))

        for i in range(self.nx):
            xKoor = self.x0 + (i - 0.5) * self.dx
            if xKoor < 1 and xKoor > -1:
                uIc[0, i] = 1.0
                uIc[1, i] = 0.0
                uIc[2, i] = 0.5
                if self.polyDegree == 3:
                    N1 = uIc[1, i] / uIc[0, i]
                    N2 = uIc[2, i] / uIc[0, i]
                    upper = N2 - (N1 - N2) ** 2 / (1 - N1)
                    lower = - N2 + (N1 + N2) ** 2 / (1 + N1)
                    uIc[3, i] = (upper + lower / 2) * uIc[0, i]
            else:
                uIc[0, i] = 0.5
                uIc[1, i] = 0.0
                uIc[2, i] = 0.25
                if self.polyDegree == 3:
                    N1 = uIc[1, i] / uIc[0, i]
                    N2 = uIc[2, i] / uIc[0, i]
                    upper = N2 - (N1 - N2) ** 2 / (1 - N1)
                    lower = - N2 + (N1 + N2) ** 2 / (1 + N1)
                    uIc[3, i] = (upper + lower / 2) * uIc[0, i]

            # uIc[0, i] = sincos(x=xKoor)
            # uIc[1, i] = 0.0  # 0.8 * uIc[0, i]  # 0.5 * uIc[0, i]  # realizable
            # uIc[2, i] = 0.1 * uIc[0, i]  # 1 + (0.8 ** 2 + 0.05) * uIc[
            #    0, i]  # uIc[1, i] ** 2 + 0.1  # uIc[1, i] ** 2 + (1 - uIc[1, i] ** 2) / 2  # realizable

            # if self.polyDegree == 3:
            #    N1 = uIc[1, i] / uIc[0, i]
            #    N2 = uIc[2, i] / uIc[0, i]
            #    uIc[3, i] = -N2 + (N1 + N2) ** 2 / (1 + N1) + 0.002  # error!
        return uIc

    def solve(self, maxIter=100):
        # self.showSolution(0)
        for idx_time in range(maxIter):  # time loop
            self.solveIterNewton(idx_time)
            self.solverIterML(idx_time)
            print("Iteration: " + str(idx_time))
            self.errorAnalysis(idx_time)
            # print iteration results
            self.showSolution(idx_time)

        return self.u

    def solveAnimationIterError(self, maxIter=100):
        fps = 1 / self.dt

        # First set up the figure, the axis, and the plot element we want to animate
        fig, ax = plt.subplots()

        ax.set_xlim((-1.5, 1.5))
        ax.set_ylim((-0.15, 1.15))
        line1, = ax.plot([], [], "ro", label="u0_ML")
        line2, = ax.plot([], [], "ro", label="u1_ML")
        line3, = ax.plot([], [], "ro", label="u2_ML")

        line4, = ax.plot([], [], "k-", label="u0_trad")
        line5, = ax.plot([], [], "k--", label="u1_trad")
        line6, = ax.plot([], [], "k:", label="u2_trad")

        if self.polyDegree == 3:
            line7, = ax.plot([], [], "ro", label="u3_ML")
            line8, = ax.plot([], [], "k.", label="u3_trad")

        x = np.linspace(self.x0, self.x1, self.nx)

        ax.legend()

        def animate_func(i):
            # entropy closure and
            self.entropyClosureNewton()
            # reconstruction
            self.realizabilityReconstruction()
            # entropy closure and
            self.entropyClosureML()
            self.compareAndRetrain()

            # flux computation
            self.computeFluxNewton()
            # FVM update
            self.FVMUpdateNewton()

            # flux computation
            self.computeFluxML()
            # FVM update
            self.FVMUpdateML()

            # self.solveIterNewton(i)
            # self.solverIterML(i)

            # step by step execution

            # self.compareAndRetrain()

            print("Iteration: " + str(i))

            # ax.plot(x, self.u2[0, :])
            line1.set_data(x, self.u2[0, :])
            line2.set_data(x, self.u2[1, :])
            line3.set_data(x, self.u2[2, :])
            if self.polyDegree == 3:
                line7.set_data(x, self.u2[3, :])
            line4.set_data(x, self.u[0, :])
            line5.set_data(x, self.u[1, :])
            line6.set_data(x, self.u[2, :])
            if self.polyDegree == 3:
                line8.set_data(x, self.u[3, :])
                return [line1, line2, line3, line4, line5, line6, line7, line8]

            return [line1, line2, line3, line4, line5, line6]

        # anim = animation.FuncAnimation(fig, animate_func, frames=maxIter, interval=10000 * self.dt)
        anim = animation.FuncAnimation(fig, animate_func, frames=maxIter, interval=20000 * self.dt, blit=True)
        if self.traditional:
            filename = "newton_version.gif"
        else:
            filename = "ErrorPerIter.gif"
        # anim.save('ErrorPerIter.gif', writer='imagemagick', fps=60)
        anim.save(filename, writer=animation.PillowWriter(fps=fps))

    def solveIterNewton(self, t_idx):
        # entropy closure and
        self.entropyClosureNewton()
        # reconstruction
        self.realizabilityReconstruction()
        # flux computation
        self.computeFluxNewton()
        # FVM update
        self.FVMUpdateNewton()
        return 0

    def solverIterML(self, t_idx):
        # entropy closure and
        self.entropyClosureML()
        # flux computation
        self.computeFluxML()
        # FVM update
        self.FVMUpdateML()
        return 0

    def entropyClosureNewton(self):

        # if (self.traditional): # NEWTON
        for i in range(self.nx):
            self.entropyClosureSingleRow(i)
        return 0

    def entropyClosureSingleRow(self, i):
        rowRes = 0

        opti_u = self.u[:, i]
        alpha_init = self.alpha[:, i]
        # test objective functions
        # t = self.create_opti_entropy(opti_u)(alpha_init)
        # tp = self.create_opti_entropy_prime(opti_u)(alpha_init)
        # print(t)
        # print(tp)
        normU = np.abs(self.u[1, i])
        u0 = self.u[0, i]
        if u0 == 0:
            print("u0 = 0")
        elif normU / u0 > 0.95:
            print("Warning")
        opt_result = scipy.optimize.minimize(fun=self.create_opti_entropy(opti_u), x0=alpha_init,
                                             jac=self.create_opti_entropy_prime(opti_u),
                                             tol=1e-7)
        if not opt_result.success:
            print("Optimization unsuccessfull! u=" + str(opti_u))
            exit(ValueError)
        else:
            self.alpha[:, i] = opt_result.x
            rowRes = opt_result.x
            self.h[i] = opt_result.fun
        return rowRes

    def create_opti_entropy(self, u):

        def opti_entropy(alpha):
            """
            brief: returns the negative entropy functional with fixed u

            nS = batchSize
            N = basisSize
            nq = number of quadPts

            input: alpha, dims = (1 x N)
                   u, dims = (1 x N)
            used members: m    , dims = (N x nq)
                        w    , dims = nq

            returns h = - alpha*u + <eta_*(alpha*m)>
            """
            # Currently only for maxwell Boltzmann entropy
            # compute negative entropy functional
            f_quad = np.exp(np.tensordot(alpha, self.mBasis, axes=([0], [0])))  # alpha*m
            t1 = np.tensordot(f_quad, self.quadWeights, axes=([0], [0]))  # f*w
            t2 = np.inner(alpha, u)

            return t1 - t2

        return opti_entropy

    def create_opti_entropy_prime(self, u):

        def opti_entropy_prime(alpha):
            """
             brief: returns the derivative negative entropy functional with fixed u
             nS = batchSize
             N = basisSize
             nq = number of quadPts

             input: alpha, dims = (1 x N)
                    u, dims = (1 x N)
             used members: m    , dims = (N x nq)
                         w    , dims = nq

             returns h = - alpha + <m eta_*(alpha*m)>
            """
            # Currently only for maxwell Boltzmann entropy

            f_quad = np.exp(np.tensordot(alpha, self.mBasis, axes=([0], [0])))  # alpha*m
            tmp = np.multiply(f_quad, self.quadWeights)  # f*w
            t2 = np.tensordot(tmp, self.mBasis, axes=([0], [1]))  # f * w * momentBasis
            return t2 - u

        return opti_entropy_prime

    def create_opti_entropy_prime2nd(self, u):

        def opti_entropy_prime2nd(alpha):
            """ #TODO
             brief: returns the derivative negative entropy functional with fixed u
             nS = batchSize
             N = basisSize
             nq = number of quadPts

             input: alpha, dims = (1 x N)
                    u, dims = (1 x N)
             used members: m    , dims = (N x nq)
                         w    , dims = nq

             returns h = <mxm eta_*(alpha*m)>
            """
            # Currently only for maxwell Boltzmann entropy

            f_quad = np.exp(np.tensordot(alpha, self.mBasis, axes=([0], [0])))  # alpha*m
            tmp = np.multiply(f_quad, self.quadWeights)  # f*w
            t2 = np.tensordot(tmp, self.mBasis, axes=([0], [1]))  # f * w * momentBasis
            return t2 - u

        return opti_entropy_prime2nd

    def realizabilityReconstruction(self):

        for i in range(self.nx):
            # self.u2[:, i] = np.copy(self.u[:, i])
            a = np.reshape(self.alpha[:, i], (1, self.nSystem))
            self.u[:, i] = math.reconstructU(alpha=a, m=self.mBasis, w=self.quadWeights)
            # print("(" + str(self.u2[:, i]) + " | " + str(self.u[:, i]))
            # h = self.create_opti_entropy(self.u[:, i])(self.alpha[:, i])
            # row = [0, self.u[0, i], self.u[1, i], self.u[2, i], self.alpha[0, i], self.alpha[1, i],
            #       self.alpha[2, i], h]

        return 0

    def compareAndRetrain(self):
        # open the file in the write mode
        with open('csv_writeout/Monomial_M2_1D.csv', 'a+', newline='') as f:
            # create the csv writer
            writer = csv.writer(f)
            for i in range(self.nx):
                h = self.create_opti_entropy(self.u[:, i])(self.alpha[:, i])
                row = [0, self.u[0, i], self.u[1, i], self.u[2, i], self.alpha[0, i], self.alpha[1, i],
                       self.alpha[2, i], h]
                writer.writerow(row)

                h = self.create_opti_entropy(self.u2[:, i])(self.alpha2[:, i])
                row = [1, self.u2[0, i], self.u2[1, i], self.u2[2, i], self.alpha2[0, i], self.alpha2[1, i],
                       self.alpha2[2, i], h]
                # write a row to the csv file
                writer.writerow(row)
        return 0

    def computeFluxNewton(self):
        """
        for periodic boundaries, upwinding.
        writes to xFlux and yFlux, uses alpha
        """
        for i in range(self.nx):

            # Computation in x direction
            im1 = i - 1
            if i == 0:  # periodic boundaries
                im1 = self.nx - 1
            left = np.tensordot(self.alpha[:, im1], self.mBasis, axes=([0], [0]))
            right = np.tensordot(self.alpha[:, i], self.mBasis, axes=([0], [0]))
            fluxL = math.entropyDualPrime(left)
            fluxR = math.entropyDualPrime(right)
            flux = 0
            for q in range(self.nq):  # integrate upwinding result
                upwind = self.upwinding(fluxL[q], fluxR[q], self.quadPts[q])
                flux = flux + upwind * self.quadWeights[q] * self.mBasis[:, q]
            self.xFlux[:, i] = flux
        return 0

    def upwinding(self, fluxL, fluxR, quadpt):
        # t = np.inner(quadpt, normal)
        if quadpt > 0:
            return quadpt * fluxL
        else:
            return quadpt * fluxR

    def FVMUpdateNewton(self):
        for i in range(self.nx):
            ip1 = i + 1
            # periodic boundaries
            if i == self.nx - 1:
                ip1 = 0

            # Advection
            self.u[:, i] = self.u[:, i] + ((self.xFlux[:, i] - self.xFlux[:, ip1]) / self.dx) * self.dt
            # Scattering
            # self.u[0, i, j] = self.u[0, i, j] + (
            #        self.sigmaS * self.u[0, i, j] - self.sigmaT * self.u[0, i, j]) * self.dt
            # self.u[1:, i, j] = self.u[0, i, j] + (self.sigmaT * self.u[1:, i, j]) * self.dt

        return 0

    def entropyClosureML(self):
        tmp = np.copy(np.transpose(self.u2))
        [u_pred, alpha_pred, h] = self.neuralClosure.call_scaled_64(np.asarray(tmp))

        for i in range(self.nx):
            # self.u2[:, i] = u_pred[i, :]
            t = alpha_pred[i, :].numpy()
            a = t.reshape((1, self.nSystem))
            # self.u2[:, i] = math.reconstructU(alpha=a, m=self.mBasis, w=self.quadWeights)
            self.alpha2[:, i] = alpha_pred[i, :]
            self.h2[i] = h[i]
            # print("(" + str(self.u2[:, i]) + " | " + str(tmp[i, :]) + " | " + str(
            #    np.linalg.norm(self.u2[:, i] - tmp[i, :], 2)))
        return 0

    def computeFluxML(self):
        """
        for periodic boundaries, upwinding.
        writes to xFlux and yFlux, uses alpha
        """
        for i in range(self.nx):

            # Computation in x direction
            im1 = i - 1
            if i == 0:  # periodic boundaries
                im1 = self.nx - 1
            left = np.tensordot(self.alpha2[:, im1], self.mBasis, axes=([0], [0]))
            right = np.tensordot(self.alpha2[:, i], self.mBasis, axes=([0], [0]))
            fluxL = math.entropyDualPrime(left)
            fluxR = math.entropyDualPrime(right)
            flux = 0
            for q in range(self.nq):  # integrate upwinding result
                upwind = self.upwinding(fluxL[q], fluxR[q], self.quadPts[q])
                flux = flux + upwind * self.quadWeights[q] * self.mBasis[:, q]
            self.xFlux2[:, i] = flux
        return 0

    def FVMUpdateML(self):
        for i in range(self.nx):
            ip1 = i + 1
            # periodic boundaries
            if i == self.nx - 1:
                ip1 = 0

            # Advection
            self.u2[:, i] = self.u2[:, i] + ((self.xFlux2[:, i] - self.xFlux2[:, ip1]) / self.dx) * self.dt
            # Scattering
            # self.u[0, i, j] = self.u[0, i, j] + (
            #        self.sigmaS * self.u[0, i, j] - self.sigmaT * self.u[0, i, j]) * self.dt
            # self.u[1:, i, j] = self.u[0, i, j] + (self.sigmaT * self.u[1:, i, j]) * self.dt

        return 0

    def showSolution(self, idx):
        plt.clf()
        x = np.linspace(self.x0, self.x1, self.nx)

        plt.plot(x, self.u[0, :], "k-", label="Newton closure")
        plt.plot(x, self.u2[0, :], 'o', markersize=6, markerfacecolor='orange',
                 markeredgewidth=1.5, markeredgecolor='k', label="Neural closure")
        plt.xlim([-1.5, 1.5])
        plt.ylim([0.4, 1.1])
        plt.xlabel("x")
        plt.ylabel("u1")
        plt.legend()
        plt.savefig("00u_1_comparison_" + str(idx) + ".png", dpi=450)
        plt.clf()
        # plt.show()
        return 0

    def errorAnalysis(self, iter):
        entropyOrig = - self.h.sum() * self.dx
        entropyML = self.h2.sum() * self.dx

        # mean absulote error
        with open('00errorAnalysis1D.csv', 'a+', newline='') as f:
            # create the csv writer
            writer = csv.writer(f)
            row = [iter, entropyOrig, entropyML]
            writer.writerow(row)
        return 0


if __name__ == '__main__':
    main()
